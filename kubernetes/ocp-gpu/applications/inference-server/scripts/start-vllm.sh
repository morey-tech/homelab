#!/bin/bash
# Auto-detect optimal max-model-len for vLLM
# This script handles two error cases:
# 1. KV cache capacity exceeded
# 2. Model max_position_embeddings exceeded

# Read the full model path written by init container
MODEL_PATH=$(cat /model/.model_path)
echo "Using model path: $MODEL_PATH"

# Use env vars with defaults
GPU_UTIL=${GPU_MEMORY_UTILIZATION:-0.95}
MAX_LEN=${MAX_MODEL_LEN_START:-999999}

while true; do
  echo "Attempting vLLM with max-model-len=$MAX_LEN"

  OUTPUT=$(python -m vllm.entrypoints.openai.api_server \
    --port=8000 \
    --model=$MODEL_PATH \
    --served-model-name=$SERVED_MODEL_NAME \
    --tensor-parallel-size=1 \
    --max-model-len=$MAX_LEN \
    --dtype=auto \
    --gpu-memory-utilization=$GPU_UTIL 2>&1) &

  VLLM_PID=$!
  sleep 30

  # Check if process is still running (successful start)
  if kill -0 $VLLM_PID 2>/dev/null; then
    echo "vLLM started successfully with max-model-len=$MAX_LEN"
    wait $VLLM_PID
    exit $?
  fi

  wait $VLLM_PID
  EXIT_CODE=$?

  # Error 1: KV cache capacity exceeded
  if echo "$OUTPUT" | grep -q "larger than the maximum number of tokens that can be stored in KV cache"; then
    ACTUAL_CAPACITY=$(echo "$OUTPUT" | grep -oP 'KV cache \(\K[0-9]+')
    if [ -n "$ACTUAL_CAPACITY" ]; then
      echo "Detected KV cache capacity: $ACTUAL_CAPACITY tokens"
      MAX_LEN=$ACTUAL_CAPACITY
      continue
    fi
  fi

  # Error 2: Model max_position_embeddings exceeded
  if echo "$OUTPUT" | grep -q "max_position_embeddings"; then
    MODEL_MAX=$(echo "$OUTPUT" | grep -oP 'max_position_embeddings=\K[0-9]+')
    if [ -n "$MODEL_MAX" ]; then
      echo "Detected model max position embeddings: $MODEL_MAX tokens"
      MAX_LEN=$MODEL_MAX
      continue
    fi
  fi

  # Failed for another reason
  echo "$OUTPUT"
  exit $EXIT_CODE
done
