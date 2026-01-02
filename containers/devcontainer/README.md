# devcontainer

Development container for homelab infrastructure work, with pre-installed tools for Kubernetes, GitOps, and Infrastructure as Code.

## Tools Included

| Category | Tools |
|----------|-------|
| Kubernetes | oc/kubectl (OKD 4.17), kubectx/kubens, k9s, kustomize, kubeneat, konfig |
| GitOps | argocd, helm, kubeseal |
| IaC | terraform, vcluster |
| Cloud | ocm (OpenShift Cluster Manager), gh (GitHub CLI) |
| Python | ansible, ansible-lint, black, yamllint, proxmoxer |

## GitHub CLI Authentication

- **DevSpaces**: Automatically authenticated using OAuth credentials
- **Local DevContainer**: Requires manual `gh auth login`

## Build

```bash
podman build -t devcontainer:latest .
```

## Usage

This image is designed to be used as a VS Code devcontainer base image.

Future: Update `.devcontainer/devcontainer.json` to use:
```json
{
  "image": "ghcr.io/<owner>/homelab/devcontainer:latest"
}
```

Instead of:
```json
{
  "build": {
    "dockerfile": "Dockerfile"
  }
}
```

## User

Runs as `morey-tech` user (UID 1001) with sudo privileges.
