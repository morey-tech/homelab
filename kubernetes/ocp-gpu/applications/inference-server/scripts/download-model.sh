#!/bin/bash
# Download model from HuggingFace Hub
# Supports both full repo downloads and specific file downloads

echo "Install hf CLI with PIP"
pip install -U "huggingface_hub==1.1.4"
echo -----------------------------------

# Create workspace directory based on sanitized repo name (org_repo)
WORKSPACE_DIR=$(echo "$MODEL_REPO" | tr '/' '_')
mkdir -p /models/$WORKSPACE_DIR

if [ -z "$MODEL_FILE" ]; then
  # Download entire repo - vLLM needs the directory path
  echo "Downloading entire repo: $MODEL_REPO"
  hf download $MODEL_REPO --local-dir=/models/$WORKSPACE_DIR
  # For full repos, vLLM uses the directory (where .cache and model files live)
  ACTUAL_MODEL_PATH="/model/$WORKSPACE_DIR"
else
  # Download specific file from repo
  echo "Downloading specific file: $MODEL_REPO / $MODEL_FILE"
  hf download $MODEL_REPO $MODEL_FILE --local-dir=/models/$WORKSPACE_DIR
  # For single files, vLLM uses the full file path
  ACTUAL_MODEL_PATH="/model/$WORKSPACE_DIR/$MODEL_FILE"
fi

echo "Model path will be: $ACTUAL_MODEL_PATH"
# Write the full path for main container to use
echo $ACTUAL_MODEL_PATH > /models/.model_path
echo -----------------------------------
