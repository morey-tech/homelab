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
RESPONSE=$(curl -s --insecure -w "\n%{http_code}" -X POST "$URL" \
	-H "Content-Type: application/json" \
	--data '{
		"model": "'"$MODEL"'",
		"messages": [
			{
				"role": "user",
				"content": "'"$MESSAGE"'"
			}
		]
	}')

# Extract HTTP status code (last line) and body (everything else)
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

# Check if curl failed or returned non-2xx status
if [ -z "$HTTP_CODE" ] || [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
	echo "Error: Request failed with HTTP status code: $HTTP_CODE" >&2
	echo "Response: $BODY" >&2
	exit 1
fi

# Success - pipe to jq
echo "$BODY" | jq .choices[0].message.content