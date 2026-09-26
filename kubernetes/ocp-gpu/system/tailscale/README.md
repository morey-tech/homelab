# Tailscale egress for Dev Spaces

This application gives OCP GPU Dev Spaces workspaces automatic, shared read-only access to OCP Home. Argo CD installs the Tailscale operator; OAuth enrolls the operator and its egress proxy. Workspace containers need only the [mounted kubeconfig](../openshift-devspaces/ocp-home-kubeconfig.yaml).

## Architecture

Both clusters run the same pinned `tailscale-operator` chart in `tailscale-system`. Each cluster enrolls with its own OAuth client, which External Secrets pulls from Bitwarden. The two operators are configured for opposite roles:

| | OCP Home ([config](../../../ocp-home/system/tailscale/kustomization.yaml)) | OCP GPU ([config](kustomization.yaml)) |
|---|---|---|
| Role | API server proxy (server) | Egress proxy (client) |
| `apiServerProxyConfig.mode` | `"true"`: identity auth + impersonation | `"false"` |
| Tailnet device / tag | `ocp-home-api` / `tag:ocp-home-api` | `ocp-gpu-devspaces` / `tag:ocp-gpu-devspaces` |
| Operator tag | `tag:ocp-home-api` | `tag:ocp-gpu-operator` |
| Supporting resources | `tailnet-readers` → `view` ClusterRoleBinding | ProxyClass, proxy-only privileged SCC, egress Service, NetworkPolicy |

Request path from a workspace:

```text
workspace: oc --context=ocp-home-tailnet get pods -A
  │  HTTPS, SNI ocp-home-api.taile3c3a8.ts.net, no credentials
  ▼
Service tailscale-system/ocp-home-api (OCP GPU)    NetworkPolicy: workspace pods only
  ▼
egress proxy pod, tailnet device ocp-gpu-devspaces  TCP forward, no TLS termination
  │  WireGuard (direct or DERP)
  ▼
OCP Home operator ocp-home-api :443                 terminates TLS, identifies caller by tailnet identity
  │  tailscale.com/cap/kubernetes grant → impersonate group tailnet-readers
  ▼
OCP Home kube-apiserver                             RBAC: tailnet-readers → view (read-only)
```

- **OCP Home** exposes its API only through the operator's in-process proxy. The [tailnet policy](../../../ocp-home/system/tailscale/tailnet-policy.json) grants TCP 443 to `tag:ocp-home-api` from `autogroup:member` and `autogroup:tagged`, mapped to `tailnet-readers`. There are no tokens or client certificates.
- **OCP GPU** declares an `ExternalName` Service annotated with `tailscale.com/tailnet-fqdn`. The operator creates a kernel-mode egress StatefulSet for it and repoints `spec.externalName` at its own headless Service.
- **Dev Spaces** mounts a [kubeconfig](../openshift-devspaces/ocp-home-kubeconfig.yaml) whose server is the in-cluster Service. Its `tls-server-name` is set to the OCP Home tailnet FQDN, so TLS runs end-to-end and is verified against the real Tailscale certificate. The [env ConfigMap](../openshift-devspaces/ocp-home-kubeconfig-env.yaml) appends this kubeconfig to `KUBECONFIG`, and the local `logged-user` context stays the default. Nothing Tailscale-related runs inside workspaces.

Consequences:

- All workspace users share the egress device's identity. OCP Home audit logs show `ocp-gpu-devspaces`, not the individual user.
- Access is read-only. Write access would need a new capability grant plus RBAC on OCP Home.
- OCP Home's `autogroup:tagged` grant already covers the egress device. Removing only the OCP GPU grant does not revoke access.
- The egress proxy is a single privileged replica. A restart briefly interrupts access.

## One-time enrollment setup

1. Merge [tailnet-policy.json](tailnet-policy.json) into the existing tailnet policy in the [access controls console](https://login.tailscale.com/admin/acls). Preserve existing rules. The fragment defines `tag:ocp-gpu-operator`, lets it own `tag:ocp-gpu-devspaces`, and grants that proxy tag TCP 443 to `tag:ocp-home-api` with Kubernetes group `tailnet-readers`. This policy is not applied by Argo CD.
2. Create a separate OAuth client in the [OAuth console](https://login.tailscale.com/admin/settings/oauth), with **Devices / Core**, **Auth Keys**, and **Services** write scopes, restricted to `tag:ocp-gpu-operator`. The operator can create proxy devices with its owned tag. Configure device approval as appropriate for unattended enrollment.
3. Create a **Login** item named exactly `ocp-gpu-tailscale-operator` in the Bitwarden vault accessible to OCP GPU External Secrets. Store the OAuth client ID as **Username** and client secret as **Password**. [operator-oauth.yaml](operator-oauth.yaml) references that unique item name; renaming it requires updating both remote references. An item UUID can be substituted in both fields if preferred. Do not reuse the OCP Home operator credentials or commit secret values.
4. Ensure Bitwarden's serving cache includes the item. Once Argo has deployed the ExternalSecret, its normal refresh will populate the `operator-oauth` Secret in `tailscale-system`. Missing credentials leave the operator pending until the item becomes available.

The target is `ocp-home-api.taile3c3a8.ts.net`. Both [ocp-home-api.yaml](ocp-home-api.yaml) and the workspace kubeconfig must use that same FQDN. The Service routes to it through Tailscale; the kubeconfig uses it for TLS verification and SNI while connecting to the Kubernetes Service address.

The existing OCP Home policy grants read-only access to all tagged devices already. This dedicated tag and explicit grant document this integration, but do not narrow that existing broader grant. Policy grants and Kubernetes RBAC are additive.

## Deploy through Argo CD

```bash
kustomize build --enable-helm kubernetes/ocp-gpu/system/tailscale > /tmp/ocp-gpu-tailscale.yaml
kustomize build kubernetes/ocp-gpu/system/openshift-devspaces > /tmp/ocp-gpu-devspaces.yaml
git diff --check
```

Review, commit, and push the repository changes to `main`. Allow the existing GitOps configuration application to reconcile the [system ApplicationSet](../../openshift-gitops-config/system-appset.yaml), followed by `tailscale-system` and `openshift-devspaces-system`. Do not apply the rendered resources directly.

The ApplicationSet enables server-side apply for the large Tailscale CRDs. It ignores `spec.externalName` only on `tailscale-system/ocp-home-api` and enables `RespectIgnoreDifferences`, because the operator replaces the initial `pending.invalid` value with its generated headless Service. Other Service fields remain managed by Argo.

The SCC binding and NetworkPolicy use sync wave `-1`, the operator and ProxyClass use the default wave, and the egress Service uses wave `1`. Wait for credentials and operator readiness before expecting the egress device to appear. The proxy is a single replica; a restart temporarily interrupts access.

After the applications sync, stop/start a Dev Spaces workspace to mount `/etc/ocp-home/kubeconfig` and receive the managed `KUBECONFIG` environment variable, then follow the [workspace guide](../openshift-devspaces/TAILSCALE.md). Both ConfigMaps use `mount-on-start` to avoid restarting active workspaces automatically. No image rebuild, devfile update, browser login, or per-workspace device state is required.

## OpenShift permissions and network access

The pinned operator version is `1.102.4`. Its kernel-mode egress StatefulSet contains a privileged `sysctler` init container and a privileged Tailscale container. [proxy-scc.yaml](proxy-scc.yaml) grants the built-in `privileged` SCC only to `system:serviceaccount:tailscale-system:proxies` using a namespaced RoleBinding. This permission allows those proxy pods privileged access on their worker node. [proxyclass.yaml](proxyclass.yaml) explicitly runs these containers as UID 0. The operator itself remains non-root with dropped capabilities; workspaces receive no new SCC permission.

OAuth credentials and proxy device state stay in Kubernetes Secrets in `tailscale-system`. Preserve these Secrets across restarts to retain device identity. The chart's proxy account has Secret permissions in this namespace, so treat the operator namespace and its privileged proxy pods as trusted infrastructure.

[networkpolicy.yaml](networkpolicy.yaml) selects the operator-generated pods for this specific egress Service. It permits TCP 443 only from pods carrying a DevWorkspace ID in namespaces labelled as Dev Spaces workspace namespaces. UDP 41641 remains available for authenticated WireGuard transport. Outbound traffic is not restricted, allowing Kubernetes API, DNS, control-plane, DERP, and direct peer connections.

This policy limits access to this proxy, but does not isolate mutually untrusted workspace owners: callers share its identity, namespace owners may control labels, and users authorized to create operator-managed Services could request additional proxies. Kubernetes administrators retain their usual access.

## Verify after rollout

Use the existing OCP GPU context for these read-only checks:

```bash
oc -n openshift-gitops get application tailscale-system openshift-devspaces-system
oc -n tailscale-system get externalsecret operator-oauth
oc -n tailscale-system get deployment,statefulset,pods,service,networkpolicy
oc -n tailscale-system rollout status deployment/operator --timeout=180s
oc -n tailscale-system get service ocp-home-api -o jsonpath='{.spec.externalName}{"\n"}'
oc -n tailscale-system get pods -l tailscale.com/parent-resource=ocp-home-api \
  -o custom-columns='NAME:.metadata.name,SCC:.metadata.annotations.openshift\.io/scc,READY:.status.containerStatuses[*].ready'
oc -n admin-devspaces get configmap ocp-home-kubeconfig ocp-home-kubeconfig-env
```

The operator should use its ordinary restricted SCC, while the egress pod uses `privileged`. Confirm that the Service's `externalName` now refers to an operator-generated Service and that Argo remains Synced after reconciliation.

From a restarted workspace:

```bash
oc --context=ocp-home-tailnet auth whoami -o json
oc --context=ocp-home-tailnet get pods --all-namespaces
oc --context=ocp-home-tailnet auth can-i get secrets --all-namespaces
oc --context=ocp-home-tailnet auth can-i create deployments --all-namespaces
curl --fail --show-error --noproxy '*' \
  --connect-to ocp-home-api.taile3c3a8.ts.net:443:ocp-home-api.tailscale-system.svc.cluster.local:443 \
  https://ocp-home-api.taile3c3a8.ts.net/version
```

Expect the proxy's FQDN as username and `tailnet-readers` as a group. Pod listing succeeds; secret reads and deployment creation should report `no`. TLS verification must succeed. Repeat after stopping/starting the workspace; authentication should remain automatic. From an existing ordinary pod outside a matching workspace namespace, verify that TCP 443 to the egress Service is blocked. No test pod is deployed by this change.

## Validation performed before deployment

Both Kustomize applications render successfully. Local checks passed for the pinned ProxyClass CRD schema and cluster scope, the proxy-only SCC subject, restricted operator settings, absence of API impersonation permissions and embedded credentials, NetworkPolicy selectors, the rendered ApplicationSet template and drift rules, and matching Service/TLS hostnames. The local `oc` client parses the mounted kubeconfig with an empty user entry. Relative documentation links and `git diff --check` pass.

Read-only cluster inspection confirmed the existing SCC role, workspace labels, GitOps Helm rendering support, and the `openshift-gitops-config` application tracking this path. No resources were applied, no OAuth credentials were created, and no live egress enrollment or authorization checks were performed. Verify admission, network-policy enforcement, TLS/SNI forwarding, and identity/RBAC after your commit and push trigger Argo deployment.

## Troubleshooting and removal

- Operator awaiting its Secret: confirm the Bitwarden item name, vault cache, OAuth scopes, and ExternalSecret conditions without printing credential values.
- Proxy admission failure: inspect pod events, the proxy service account, the SCC RoleBinding, and namespace Pod Security admission. The ApplicationSet labels this namespace for privileged workloads.
- No proxy or pending Service: inspect operator logs, ProxyClass status, OAuth tag ownership, and device approval.
- TLS failure: verify both copies of the target FQDN. Do not disable certificate verification.
- API 403: check the source proxy tag, OCP Home destination tag, Kubernetes capability grant, and `tailnet-readers` binding.
- Rotate credentials through Bitwarden and External Secrets, then arrange an operator rollout through GitOps. Existing proxy state is independent of the OAuth secret.
- To remove access, revoke the egress device or its effective tailnet permissions, remove the workspace ConfigMap and egress Service through GitOps, and let the operator clean up before uninstalling it. Removing only the dedicated grant will not revoke access while the broader `autogroup:tagged` grant applies. Remove the SCC binding when no proxies remain. The ApplicationSet uses `create-update`: deleting the directory alone does not delete its Application.

## References

- [Operator installation and OAuth](https://tailscale.com/docs/kubernetes-operator/install-operator)
- [Egress architecture](https://tailscale.com/docs/kubernetes-operator/egress)
- [Pinned proxy pod template](https://github.com/tailscale/tailscale/blob/v1.102.4/cmd/k8s-operator/deploy/manifests/proxy.yaml)
- [Tagged-device API authentication](https://tailscale.com/docs/kubernetes-operator/api-server-access/auth-and-rbac)
- [OCP Home API configuration](../../../ocp-home/system/tailscale/README.md)
