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

The [OCP GPU Dev Spaces configuration](../../kubernetes/ocp-gpu/system/openshift-devspaces/TAILSCALE.md) mounts the OCP Home proxy kubeconfig at `/etc/ocp-home/kubeconfig`. The image's [ocp-home-kubeconfig.sh](ocp-home-kubeconfig.sh), installed in `~/.bashrc.d`, exports `KUBECONFIG=$HOME/.kube/config:/etc/ocp-home/kubeconfig` in interactive shells when that mount exists.

```bash
oc config get-contexts
oc get pods                                      # Local OCP GPU cluster (default)
oc --context=ocp-home-tailnet get pods -A         # OCP Home through Tailscale
```

The additional context is read-only and uses the shared proxy identity. Outside Dev Spaces the mount is absent, so the snippet does nothing.

Do not set `KUBECONFIG` as an image `ENV` or container environment variable. The Dev Spaces dashboard writes the user's kubeconfig to the directory derived from `KUBECONFIG`, and cannot handle a multi-path value ([eclipse-che/che#23972](https://github.com/eclipse-che/che/issues/23972)).

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
