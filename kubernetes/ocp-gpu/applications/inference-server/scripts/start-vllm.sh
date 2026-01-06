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
  #
  # Use fp16 explicitly instead of auto. The auto setting uses whatever dtype
  # the model config specifies, but this instance is deployed on a GTX 3090
  # (SM86, pre-SM90). On pre-SM90 GPUs, the Marlin quantization kernel's bf16
  # atomic ops must be emulated in software, while fp16 atomics have native
  # hardware support. Using fp16 avoids this performance penalty.
  python -m vllm.entrypoints.openai.api_server \
    --port=8000 \
    --model=$MODEL_PATH \
    --served-model-name=$SERVED_MODEL_NAME \
    --tensor-parallel-size=1 \
    --max-model-len=$MAX_LEN \
    --dtype=float16 \
    --gpu-memory-utilization=$GPU_UTIL \
    --enable-auto-tool-choice \
    --tool-call-parser=hermes > >(tee $OUTPUT_FILE) 2>&1 &

  VLLM_PID=$!

  # Poll for success or failure (up to 5 minutes)
  # Success = "Application startup complete" in output
  # Failure = process died
  for i in $(seq 1 300); do
    # Check for success message (vLLM is ready to serve)
    if grep -q "Application startup complete" $OUTPUT_FILE 2>/dev/null; then
      echo "vLLM started successfully with max-model-len=$MAX_LEN, gpu-memory-utilization=$GPU_UTIL"
      wait $VLLM_PID
      exit $?
    fi

    # Check if process died
    if ! kill -0 $VLLM_PID 2>/dev/null; then
      break
    fi

    sleep 1
  done

  # Process died or timed out - get exit code and parse errors
  if kill -0 $VLLM_PID 2>/dev/null; then
    echo "Timeout waiting for vLLM to start (5 minutes). Killing process."
    kill $VLLM_PID 2>/dev/null
  fi
  wait $VLLM_PID 2>/dev/null
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
    GPU_UTIL=$(awk "BEGIN {print $GPU_UTIL - 0.01}")
    echo "CUDA OOM detected. Reducing GPU utilization to $GPU_UTIL"
    continue
  fi

  # Failed for another reason - output already visible via tee
  echo "vLLM failed with exit code $EXIT_CODE"
  exit $EXIT_CODE
done
