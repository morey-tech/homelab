#!/usr/bin/env python3
"""Verify TLS, token authentication, model discovery, and streaming inference."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def oc(*args):
    return subprocess.check_output(["oc", *args], text=True).strip()


def post_json(base_url, headers, path, payload):
    request = urllib.request.Request(
        base_url + path, headers=headers, data=json.dumps(payload).encode()
    )
    with urllib.request.urlopen(request, timeout=540) as response:
        return json.load(response)


def long_context_test(base_url, headers, models):
    model = next(model for model in models["data"] if model["id"] == "local-llm")
    if model.get("max_model_len", 0) < 32768:
        raise RuntimeError("Long-context test requires the 32K server rollout first")

    prepared = []
    for word in ("red", "blue", "green"):
        # Distinct prefixes avoid sharing most KV blocks across test requests.
        content = f"Test {uuid.uuid4().hex}. Read the following filler:\n"
        content += (word + " ") * 31000
        content += "\nNow reply with a short greeting."
        payload = {
            "model": "local-llm",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 1024,
            "temperature": 0,
        }
        tokens = post_json(base_url, headers, "/tokenize", {
            "model": payload["model"], "messages": payload["messages"],
            "add_generation_prompt": True,
        })["count"]
        if not 30000 <= tokens <= 32768 - payload["max_tokens"]:
            raise RuntimeError(f"Unexpected long-prompt token count: {tokens}")
        prepared.append((payload, tokens))

    def complete(item):
        payload, expected_tokens = item
        start = time.monotonic()
        result = post_json(base_url, headers, "/v1/chat/completions", payload)
        if not result["choices"][0]["message"].get("content", "").strip():
            raise RuntimeError("Long-context completion was empty")
        if result.get("usage", {}).get("prompt_tokens") != expected_tokens:
            raise RuntimeError("Long-context prompt token usage did not match tokenizer count")
        return f"{expected_tokens} prompt tokens in {time.monotonic() - start:.1f}s"

    print("PASS: single long-context request:", complete(prepared[0]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(complete, prepared[1:]))
    print("PASS: two concurrent long-context client requests:", "; ".join(results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--long-context", action="store_true",
        help="After the 32K rollout, also test one then two concurrent ~31K-token prompts.",
    )
    args = parser.parse_args()
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

    duration = "30m" if args.long_context else "10m"
    token = oc("create", "token", "inference-client", "-n", "inference-server", "--duration=" + duration)
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
    if args.long_context:
        long_context_test(base_url, headers, models)
    print("Endpoint:", base_url + "/v1")


if __name__ == "__main__":
    main()
