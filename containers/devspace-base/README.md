# devspace-base

Base development container image extending Red Hat Universal Developer Image (UDI) with Claude CLI and GitHub CLI.

## Purpose

This image serves as the foundation for all morey-tech devspace containers. It provides:
- All tools included in Red Hat UDI (kubectl, oc, helm, kustomize, terraform, kubectx, kubens)
- GitHub CLI (gh) for GitHub operations
- Claude CLI for AI-assisted development

## Tools Included

### From Red Hat UDI
- **Kubernetes**: kubectl, oc (OpenShift CLI)
- **Kubernetes Utilities**: kubectx, kubens
- **GitOps**: helm, kustomize
- **Infrastructure as Code**: terraform

### Added in devspace-base
- **GitHub**: gh (GitHub CLI)
- **AI Assistant**: claude (Claude CLI)

## Base Image

- **Upstream**: `quay.io/devfile/universal-developer-image:ubi9-latest`
- **Architecture**: Multi-arch (linux/amd64, linux/arm64)

## Build

```bash
podman build -t devspace-base:latest ./containers/devspace-base
```

## Usage

This image is designed to be extended by project-specific devcontainers:

```dockerfile
FROM ghcr.io/morey-tech/homelab/devspace-base:latest

# Add your project-specific tools here
```

## User

Runs as `user` (UID 1001, GID 1001) - the default user from Red Hat UDI.

## CLIs

GitHub CLI and Claude CLI are installed and added to PATH.

To verify installations:
```bash
gh --version
claude --version
```

## Compatibility

- **OpenShift DevSpaces**: Fully compatible
- **VS Code DevContainers**: Fully compatible
- **Podman/Docker**: Direct usage supported
