#!/bin/bash
# Auto-detect optimal max-model-len for vLLM
# This script handles three error cases:
# 1. KV cache capacity exceeded
# 2. Model max_position_embeddings exceeded
# 3. CUDA out of memory (reduces GPU utilization)

# Read the full model path written by init container
MODEL_PATH=$(cat /model/.model_path)
echo "Using model path: $MODEL_PATH"

# Use env vars with defaults
GPU_UTIL=${GPU_MEMORY_UTILIZATION:-0.94}
MAX_LEN=${MAX_MODEL_LEN_START:-999999}
OUTPUT_FILE=/tmp/vllm_output.log

while true; do
  echo "Attempting vLLM with max-model-len=$MAX_LEN, gpu-memory-utilization=$GPU_UTIL"

  # Run vLLM, output to file AND stdout via tee (so we can see live output)
  # Use process substitution to get python's PID (not tee's)
  python -m vllm.entrypoints.openai.api_server \
    --port=8000 \
    --model=$MODEL_PATH \
    --served-model-name=$SERVED_MODEL_NAME \
    --tensor-parallel-size=1 \
    --max-model-len=$MAX_LEN \
    --dtype=auto \
    --gpu-memory-utilization=$GPU_UTIL > >(tee $OUTPUT_FILE) 2>&1 &

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

  # Read output from file for error parsing
  OUTPUT=$(cat $OUTPUT_FILE)

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

  # Error 3: CUDA out of memory - reduce GPU utilization by 1%
  if echo "$OUTPUT" | grep -q "CUDA out of memory"; then
    GPU_UTIL=$(echo "$GPU_UTIL - 0.01" | bc)
    echo "CUDA OOM detected. Reducing GPU utilization to $GPU_UTIL"
    continue
  fi

  # Failed for another reason - output already visible via tee
  echo "vLLM failed with exit code $EXIT_CODE"
  exit $EXIT_CODE
done
