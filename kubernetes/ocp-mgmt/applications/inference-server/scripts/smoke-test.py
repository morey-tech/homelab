#!/usr/bin/env python3
"""Verify TLS, token authentication, model discovery, and streaming inference."""

import json
import subprocess
import urllib.error
import urllib.request


def oc(*args):
    return subprocess.check_output(["oc", *args], text=True).strip()


def main():
    service = json.loads(oc("get", "inferenceservice", "local-llm", "-n", "inference-server", "-o", "json"))
    base_url = service["status"]["url"].rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("Expected a TLS inference endpoint")

    try:
        with urllib.request.urlopen(base_url + "/v1/models", timeout=30):
            raise RuntimeError("Unauthenticated model access was accepted")
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403):
            raise
    print("PASS: unauthenticated access denied")

    token = oc("create", "token", "inference-client", "-n", "inference-server", "--duration=10m")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    request = urllib.request.Request(base_url + "/v1/models", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        models = json.load(response)
    if "local-llm" not in {model["id"] for model in models["data"]}:
        raise RuntimeError("Expected local-llm in the model list")
    print("PASS: authenticated model discovery")

    payload = {
        "model": "local-llm",
        "messages": [{"role": "user", "content": "Reply with a short greeting."}],
        "max_tokens": 32,
        "temperature": 0,
    }
    request = urllib.request.Request(
        base_url + "/v1/chat/completions", headers=headers, data=json.dumps(payload).encode()
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        completion = json.load(response)
    if not completion["choices"][0]["message"].get("content"):
        raise RuntimeError("Chat completion was empty")
    print("PASS: chat completion")

    payload["stream"] = True
    request = urllib.request.Request(
        base_url + "/v1/chat/completions", headers=headers, data=json.dumps(payload).encode()
    )
    received_content = False
    received_done = False
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            line = line.decode().strip()
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            if data == "[DONE]":
                received_done = True
                break
            chunk = json.loads(data)
            received_content |= any(choice.get("delta", {}).get("content") for choice in chunk.get("choices", []))
    if not received_content or not received_done:
        raise RuntimeError("Streaming response did not contain content and a completion marker")
    print("PASS: streaming chat completion")
    print("Endpoint:", base_url + "/v1")


if __name__ == "__main__":
    main()
