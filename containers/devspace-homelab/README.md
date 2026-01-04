# devspace-homelab

Homelab-specific development container with pre-installed tools for Kubernetes, GitOps, and Infrastructure as Code.

This image extends `devspace-base` which provides Claude CLI, GitHub CLI, and base Kubernetes tools.

## Tools Included

### From devspace-base
| Category | Tools |
|----------|-------|
| Kubernetes | kubectl, oc (OpenShift CLI) |
| Kubernetes Utilities | kubectx, kubens |
| GitOps | helm, kustomize |
| Infrastructure as Code | terraform |
| Cloud | gh (GitHub CLI) |
| AI | claude (Claude CLI) |

### Added in devspace-homelab
| Category | Tools |
|----------|-------|
| Kubernetes | k9s, kubeneat, konfig |
| GitOps | argocd, kubeseal |
| IaC | vcluster |
| Cloud | ocm (OpenShift Cluster Manager) |
| Python | ansible, ansible-lint, black, yamllint, proxmoxer |

## GitHub CLI Authentication

- **DevSpaces**: Automatically authenticated using OAuth credentials
- **Local DevContainer**: Requires manual `gh auth login`

## Build

```bash
podman build -t devspace-homelab:latest ./containers/devspace-homelab
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
