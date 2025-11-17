# Call the server using curl:
curl --insecure -X POST "https://interence-server-inference-server.apps.ocp-gpu.rh-lab.morey.tech/v1/chat/completions" \
	-H "Content-Type: application/json" \
	--data '{
		"model": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
		"messages": [
			{
				"role": "user",
				"content": "What is the capital of France?"
			}
		]
	}'