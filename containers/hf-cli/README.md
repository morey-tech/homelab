# hf-cli

A container image with the Hugging Face CLI pre-installed for model downloading.

## Purpose

This image provides the `hf` command for downloading models from Hugging Face Hub. Using a pre-built image with the CLI installed enables container layer caching, avoiding pip installs at runtime.

## Build

```bash
podman build -t hf-cli:latest .
```

## Usage

Download a model:

```bash
podman run --rm -v ./models:/models:Z hf-cli:latest \
    hf download <model-repo> --local-dir=/models/<model-name>
```

Example:

```bash
podman run --rm -v ./models:/models:Z hf-cli:latest \
    hf download RedHatAI/Qwen3-30B --local-dir=/models/Qwen3-30B
```

## OpenShift Compatibility

This image is designed for OpenShift deployments:

- Runs as non-root user (UID 1001)
- User is member of GID 0 (root group) for arbitrary UID compatibility
- Writable directories have group write permissions (`g=u`)

## Environment Variables

- `HF_HOME=/model-files-cache` - Hugging Face CLI cache directory (ephemeral)

When using `--local-dir`, models are downloaded to the specified path, not `HF_HOME`.
