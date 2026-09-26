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

## Kubernetes contexts in Dev Spaces

The [OCP GPU Dev Spaces configuration](../../kubernetes/ocp-gpu/system/openshift-devspaces/TAILSCALE.md) mounts the OCP Home proxy kubeconfig and supplies `KUBECONFIG=/home/user/.kube/config:/etc/ocp-home/kubeconfig` at workspace startup. The image keeps `/home/user` as a symlink to `/home/morey-tech`, preserving the generated local kubeconfig path.

```bash
oc config get-contexts
oc get pods                                      # Local OCP GPU cluster (default)
oc --context=ocp-home-tailnet get pods -A         # OCP Home through Tailscale
```

The additional context is read-only and uses the shared proxy identity. This is configured through Argo CD-managed ConfigMaps, so it requires no image rebuild and does not change local devcontainer configuration. After those resources sync, stop/start the Dev Space to receive the mount and environment variable.

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
