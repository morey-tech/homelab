#!/usr/bin/env python3
"""Verify AnythingLLM authentication and streaming through local-llm."""

import argparse
import base64
import json
import subprocess
import urllib.error
import urllib.request
import uuid


def oc(*args):
    return subprocess.check_output(
        ["oc", "-n", "anythingllm", *args], text=True, timeout=45
    ).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--restart", action="store_true",
        help="Restart AnythingLLM after chatting to verify persistence (brief downtime).",
    )
    args = parser.parse_args()
    route = json.loads(oc("get", "route", "anythingllm", "-o", "json"))
    base_url = "https://" + route["spec"]["host"] + "/api"

    def request(path, payload=None, token=None, method=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        return urllib.request.urlopen(
            urllib.request.Request(
                base_url + path,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers=headers,
                method=method,
            ),
            timeout=180,
        )

    def request_json(path, **kwargs):
        with request(path, **kwargs) as response:
            return json.load(response)

    if not request_json("/ping").get("online"):
        raise RuntimeError("AnythingLLM is not online")
    print("PASS: HTTPS health endpoint")

    try:
        with request("/workspaces"):
            raise RuntimeError("Unauthenticated workspace access was accepted")
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
    print("PASS: unauthenticated access denied")

    secret = json.loads(oc("get", "secret", "anythingllm-auth", "-o", "json"))
    password = base64.b64decode(secret["data"]["AUTH_TOKEN"]).decode()
    login = request_json("/request-token", payload={"password": password})
    if not login.get("valid") or not login.get("token"):
        raise RuntimeError("Password authentication failed")
    token = login["token"]
    print("PASS: password authentication (credentials not displayed)")

    created = request_json(
        "/workspace/new",
        payload={"name": "smoke-test-" + uuid.uuid4().hex[:12]}, token=token,
    )
    workspace = created.get("workspace")
    if not workspace:
        raise RuntimeError("Could not create temporary test workspace")
    path = "/workspace/" + workspace["slug"]
    try:
        # Use the configured system provider/model, not a per-workspace override.
        with request(
            path + "/stream-chat",
            payload={"message": "Reply with a short greeting. /no_think"}, token=token,
        ) as response:
            fragments = []
            closed = False
            for raw_line in response:
                line = raw_line.decode().strip()
                if not line.startswith("data:"):
                    continue
                chunk = json.loads(line.removeprefix("data:").strip())
                if chunk.get("error") or chunk.get("type") == "abort":
                    raise RuntimeError("AnythingLLM reported a generation error")
                if chunk.get("textResponse"):
                    fragments.append(chunk["textResponse"])
                closed |= chunk.get("close", False)
            if not closed or not "".join(fragments).strip():
                raise RuntimeError("Streaming response was empty or incomplete")
        print("PASS: streamed chat through the configured local-llm provider")

        if args.restart:
            oc("rollout", "restart", "deployment/anythingllm")
            subprocess.run(
                ["oc", "-n", "anythingllm", "rollout", "status",
                 "deployment/anythingllm", "--timeout=10m"],
                check=True, timeout=630,
            )
            if not request_json(path, token=token).get("workspace"):
                raise RuntimeError("Workspace did not survive restart")
            history = request_json(path + "/chats", token=token).get("history", [])
            if not history:
                raise RuntimeError("Chat history did not survive restart")
            print("PASS: workspace, chat history, and login session survive restart")
    finally:
        with request(path, token=token, method="DELETE"):
            pass
        print("Removed temporary test workspace")


if __name__ == "__main__":
    main()
