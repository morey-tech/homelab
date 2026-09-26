# Automatic OCP Home access from Dev Spaces

After Argo CD syncs the Dev Spaces configuration, stop/start the workspace and run:

```bash
oc config get-contexts
oc config current-context
oc get pods
oc --context=ocp-home-tailnet auth whoami
oc --context=ocp-home-tailnet get pods --all-namespaces
```

The default remains the local OCP GPU context (`logged-user`). Use `--context=ocp-home-tailnet` when accessing OCP Home. These commands work with `kubectl` as well as `oc`.

Dev Spaces mounts a token-free kubeconfig from [ocp-home-kubeconfig.yaml](ocp-home-kubeconfig.yaml). The `devspace-homelab` image's [shell init snippet](../../../../containers/devspace-homelab/ocp-home-kubeconfig.sh), installed at `~/.bashrc.d/10-ocp-home-kubeconfig.sh`, exports this in interactive shells when the mount exists:

```bash
KUBECONFIG=$HOME/.kube/config:/etc/ocp-home/kubeconfig
```

The first file is generated and refreshed by Dev Spaces for the local cluster. The second adds the proxy context without selecting a default. Clients combine the files when reading them; local credentials are not copied into the ConfigMap. No manual export or per-workspace devfile change is required.

`KUBECONFIG` must not be set in the container environment (via a ConfigMap, devfile, or image `ENV`). The dashboard's kubeconfig injection reads `KUBECONFIG` as a single directory. A multi-path value makes it write the user's credentials to `~/.kube/config:/etc/ocp-home/kubeconfig/config`, leaving `~/.kube/config` empty, and `oc` then falls back to the workspace service account ([eclipse-che/che#23972](https://github.com/eclipse-che/che/issues/23972)). Other images must provide an equivalent shell export, or use `--kubeconfig=/etc/ocp-home/kubeconfig --context=ocp-home-tailnet`.

No Tailscale installation, browser login, or auth key is needed inside the workspace. The operator enrolls a shared egress device with OAuth credentials held in its own namespace.

All workspace callers use the egress proxy's tagged-device identity. The OCP Home API proxy maps that identity to `tailnet-readers`, whose `view` role permits read-only access. Audit logs identify the proxy's node FQDN rather than the individual Dev Spaces user. This connection does not grant administration rights.

## Select a context

Prefer `--context=ocp-home-tailnet` for individual commands so the local context stays selected. To explicitly switch the current context and then return:

```bash
oc config use-context ocp-home-tailnet
oc get pods --all-namespaces
oc config use-context logged-user
```

Context selection is written to the writable local kubeconfig. Opening another terminal does not undo an explicit context switch. Do not run `oc login` against the read-only mounted proxy kubeconfig.

For troubleshooting with only the mounted file, specify its context because it intentionally has no default:

```bash
oc --kubeconfig=/etc/ocp-home/kubeconfig --context=ocp-home-tailnet auth whoami
```

## Architecture

```text
workspace oc/kubectl
  -> ocp-home-api.tailscale-system.svc.cluster.local:443
  -> operator-managed egress proxy in OCP GPU
  -> ocp-home-api in the tailnet
  -> OCP Home Kubernetes API, impersonating the proxy identity
```

The kubeconfig's `tls-server-name` is the actual OCP Home proxy FQDN. This preserves SNI and certificate validation while connecting through Kubernetes DNS. HTTPS runs end-to-end to OCP Home; the egress proxy forwards TCP. A separate HTTP proxy and cluster-wide MagicDNS configuration are unnecessary.

Both ConfigMaps are synchronized into user namespaces by Dev Spaces. `mount-on-start` prevents their creation from interrupting active workspaces; stop/start a workspace after Argo sync to receive them. Existing workspaces do not need devfile changes. Workspaces need only `oc` or `kubectl` and normal trusted CA certificates.

See the [operator deployment guide](../tailscale/README.md) for OAuth setup, GitOps rollout, OpenShift permissions, and network isolation.

## Validate after rollout

```bash
printenv KUBECONFIG
oc config current-context
oc --context=ocp-home-tailnet config view --minify
oc --context=ocp-home-tailnet auth whoami -o json
oc --context=ocp-home-tailnet get pods --all-namespaces
oc --context=ocp-home-tailnet auth can-i list pods --all-namespaces
oc --context=ocp-home-tailnet auth can-i get secrets --all-namespaces
oc --context=ocp-home-tailnet auth can-i create deployments --all-namespaces
oc --context=ocp-home-tailnet get --raw=/version
```

Expected: the user entry is empty, with no token, certificate, or exec credential. `whoami` reports the egress device's FQDN and `tailnet-readers`. Pod listing succeeds; secret reads and deployment creation return `no` unless another RBAC grant gives that identity more access. The normal OCP GPU context must still work separately.

## Troubleshooting

- Missing file or context: verify that Argo has synced the ConfigMap, that it exists in the workspace namespace, that `/etc/ocp-home/kubeconfig` is mounted, and that `printenv KUBECONFIG` in a new terminal includes both paths; then stop/start the workspace.
- `oc whoami` reports `system:serviceaccount:...` instead of your user: `KUBECONFIG` is probably set in the container environment (check `cat /proc/1/environ | tr '\0' '\n' | grep KUBECONFIG`). Remove it, delete any `~/.kube/config:` directory, and use **Refresh kubeconfig** in the workspace's Advanced tab or stop/start the workspace.
- DNS failure: check the operator-managed Service target and proxy readiness in `tailscale-system`.
- Timeout: check proxy readiness, the workspace labels against its NetworkPolicy, and the tailnet grant to `tag:ocp-home-api` TCP 443.
- Certificate error: the Service target annotation and kubeconfig `tls-server-name` must identify the same actual OCP Home tailnet FQDN. Keep TLS verification enabled.
- HTTP 403: inspect `oc auth whoami`, the tailnet Kubernetes capability grant, and the OCP Home `tailnet-readers` binding.

## References

- [Tailscale operator egress](https://tailscale.com/docs/kubernetes-operator/egress)
- [Tagged-device identity mapping](https://tailscale.com/docs/kubernetes-operator/api-server-access/auth-and-rbac)
- [Dev Spaces ConfigMap synchronization](https://eclipse.dev/che/docs/stable/administration-guide/configuring-a-user-namespace/)
- [OCP Home API proxy](../../../ocp-home/system/tailscale/README.md)
- [Kubernetes kubeconfig merge rules](https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/#merging-kubeconfig-files)
