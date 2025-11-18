#!/usr/bin/env bash

# Usage: test.sh [message] [model] [url]
# Examples:
#   test.sh "What is the capital of France?"
#   test.sh "Explain Docker" "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M"
#   test.sh "Hello" "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M" "https://custom-url.example.com/v1/chat/completions"

# Default values
DEFAULT_MESSAGE="What is the capital of France?"
DEFAULT_MODEL="Qwen3-Coder-30B-A3B-Instruct-Q4_K_M"
DEFAULT_URL="https://interence-server-inference-server.apps.ocp-gpu.rh-lab.morey.tech/v1/chat/completions"

# Use input arguments or defaults
MESSAGE="${1:-$DEFAULT_MESSAGE}"
MODEL="${2:-$DEFAULT_MODEL}"
URL="${3:-$DEFAULT_URL}"

# Call the server using curl
curl -s --insecure -X POST "$URL" \
	-H "Content-Type: application/json" \
	--data '{
		"model": "'"$MODEL"'",
		"messages": [
			{
				"role": "user",
				"content": "'"$MESSAGE"'"
			}
		]
	}' | jq .choices[0].message.content