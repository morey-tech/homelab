# Automatic OCP Home access from Dev Spaces

After the operator egress deployment is complete and the workspace has been restarted, run:

```bash
oc --kubeconfig=/etc/ocp-home/kubeconfig auth whoami
oc --kubeconfig=/etc/ocp-home/kubeconfig get pods --all-namespaces
```

Dev Spaces mounts a token-free kubeconfig from [ocp-home-kubeconfig.yaml](ocp-home-kubeconfig.yaml). No Tailscale installation, browser login, auth key, or workspace image rebuild is needed. The operator enrolls a shared egress device with OAuth credentials held in its own namespace.

All workspace callers use the egress proxy's tagged-device identity. The OCP Home API proxy maps that identity to `tailnet-readers`, whose `view` role permits read-only access. Audit logs identify the proxy's node FQDN rather than the individual Dev Spaces user. This connection does not grant administration rights.

## Select a context

The explicit `--kubeconfig` commands above leave your normal OCP GPU credentials selected. To add the context in the current terminal while retaining your existing configuration:

```bash
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}:/etc/ocp-home/kubeconfig"
oc --context=ocp-home-tailnet get pods --all-namespaces
```

Use explicit `--context=ocp-home-tailnet` for OCP Home commands. Avoid `oc login` against this read-only mounted kubeconfig. Open a fresh terminal to return to the previous environment.

## Architecture

```text
workspace oc/kubectl
  -> ocp-home-api.tailscale-system.svc.cluster.local:443
  -> operator-managed egress proxy in OCP GPU
  -> ocp-home-api in the tailnet
  -> OCP Home Kubernetes API, impersonating the proxy identity
```

The kubeconfig's `tls-server-name` is the actual OCP Home proxy FQDN. This preserves SNI and certificate validation while connecting through Kubernetes DNS. HTTPS runs end-to-end to OCP Home; the egress proxy forwards TCP. A separate HTTP proxy and cluster-wide MagicDNS configuration are unnecessary.

The ConfigMap is synchronized into user namespaces by Dev Spaces. `mount-on-start` prevents its creation from interrupting active workspaces; stop/start a workspace after Argo sync to mount it. Existing workspaces do not need devfile changes. Workspaces need only `oc` or `kubectl` and normal trusted CA certificates.

See the [operator deployment guide](../tailscale/README.md) for OAuth setup, GitOps rollout, OpenShift permissions, and network isolation.

## Validate after rollout

```bash
(
  export KUBECONFIG=/etc/ocp-home/kubeconfig
  oc config view --minify
  oc auth whoami -o json
  oc get pods --all-namespaces
  oc auth can-i list pods --all-namespaces
  oc auth can-i get secrets --all-namespaces
  oc auth can-i create deployments --all-namespaces
  oc get --raw=/version
)
```

Expected: the user entry is empty, with no token, certificate, or exec credential. `whoami` reports the egress device's FQDN and `tailnet-readers`. Pod listing succeeds; secret reads and deployment creation return `no` unless another RBAC grant gives that identity more access. The normal OCP GPU context must still work separately.

## Troubleshooting

- Missing file: verify Argo sync and ConfigMap propagation, then stop/start the workspace.
- DNS failure: check the operator-managed Service target and proxy readiness in `tailscale-system`.
- Timeout: check proxy readiness, the workspace labels against its NetworkPolicy, and the tailnet grant to `tag:ocp-home-api` TCP 443.
- Certificate error: the Service target annotation and kubeconfig `tls-server-name` must identify the same actual OCP Home tailnet FQDN. Keep TLS verification enabled.
- HTTP 403: inspect `oc auth whoami`, the tailnet Kubernetes capability grant, and the OCP Home `tailnet-readers` binding.

## References

- [Tailscale operator egress](https://tailscale.com/docs/kubernetes-operator/egress)
- [Tagged-device identity mapping](https://tailscale.com/docs/kubernetes-operator/api-server-access/auth-and-rbac)
- [Dev Spaces ConfigMap synchronization](https://eclipse.dev/che/docs/stable/administration-guide/configuring-a-user-namespace/)
- [OCP Home API proxy](../../../ocp-home/system/tailscale/README.md)
