# Tailscale egress for Dev Spaces

This application gives the admin user's OCP GPU Dev Spaces workspaces (namespace `admin-devspaces`) automatic `cluster-admin` access to OCP Home. Argo CD installs the Tailscale operator; OAuth enrolls the operator and its egress proxy. Workspace containers need only the [mounted kubeconfig](../openshift-devspaces/ocp-home-kubeconfig.yaml).

## Architecture

Both clusters run the same pinned `tailscale-operator` chart in `tailscale-system`. Each cluster enrolls with its own OAuth client, which External Secrets pulls from Bitwarden. The two operators are configured for opposite roles:

| | OCP Home ([config](../../../ocp-home/system/tailscale/kustomization.yaml)) | OCP GPU ([config](kustomization.yaml)) |
|---|---|---|
| Role | API server proxy (server) | Egress proxy (client) |
| `apiServerProxyConfig.mode` | `"true"`: identity auth + impersonation | `"false"` |
| Tailnet device / tag | `ocp-home-api` / `tag:ocp-home-api` | `ocp-gpu-devspaces` / `tag:ocp-gpu-devspaces` |
| Operator tag | `tag:ocp-home-api` | `tag:ocp-gpu-operator` |
| Supporting resources | `tailnet-readers` → `view` and `tailnet-admins` → `cluster-admin` ClusterRoleBindings | ProxyClass, proxy-only privileged SCC, egress Service, NetworkPolicy |

Request path from a workspace:

```text
workspace: oc --context=ocp-home-tailnet get pods -A
  │  HTTPS, SNI ocp-home-api.taile3c3a8.ts.net, no credentials
  ▼
Service tailscale-system/ocp-home-api (OCP GPU)    NetworkPolicy: admin-devspaces workspace pods only
  ▼
egress proxy pod, tailnet device ocp-gpu-devspaces  TCP forward, no TLS termination
  │  WireGuard (direct or DERP)
  ▼
OCP Home operator ocp-home-api :443                 terminates TLS, identifies caller by tailnet identity
  │  tailscale.com/cap/kubernetes grants → impersonate groups tailnet-admins, tailnet-readers
  ▼
OCP Home kube-apiserver                             RBAC: tailnet-admins → cluster-admin
```

- **OCP Home** exposes its API only through the operator's in-process proxy. The [tailnet policy](https://github.com/morey-tech/homelab-private/blob/main/tailscale/policy.hujson) grants TCP 443 to `tag:ocp-home-api` from `autogroup:member` and `autogroup:tagged`, mapped to `tailnet-readers`. It also maps `tag:ocp-gpu-devspaces` to `tailnet-admins`. There are no tokens or client certificates.
- **OCP GPU** declares an `ExternalName` Service annotated with `tailscale.com/tailnet-fqdn`. The operator creates a kernel-mode egress StatefulSet for it and repoints `spec.externalName` at its own headless Service.
- **Dev Spaces** mounts a [kubeconfig](../openshift-devspaces/ocp-home-kubeconfig.yaml) whose server is the in-cluster Service. Its `tls-server-name` is set to the OCP Home tailnet FQDN, so TLS runs end-to-end and is verified against the real Tailscale certificate. The `devspace-homelab` image's [shell init snippet](../../../../containers/devspace-homelab/ocp-home-kubeconfig.sh) appends this kubeconfig to `KUBECONFIG`, and the local `logged-user` context stays the default. `KUBECONFIG` is deliberately not set container-wide ([eclipse-che/che#23972](https://github.com/eclipse-che/che/issues/23972)). Nothing Tailscale-related runs inside workspaces.

Consequences:

- The egress device has `cluster-admin` on OCP Home. The NetworkPolicy is the only thing limiting who can use it: pods in `admin-devspaces`. Anyone who can run pods in that namespace, or read Secrets and exec into pods in OCP GPU's `tailscale-system`, effectively has `cluster-admin` on OCP Home.
- OCP Home audit logs show `ocp-gpu-devspaces.taile3c3a8.ts.net`, not the individual user.
- Workspaces in other namespaces still receive the kubeconfig, which Dev Spaces syncs to every user namespace, but their connections time out.
- Removing the OCP GPU grant drops admin access. The egress device keeps `view` access through OCP Home's `autogroup:tagged` grant.
- The egress proxy is a single privileged replica. A restart briefly interrupts access.

## One-time enrollment setup

1. The tailnet policy lives in the private repo, at [homelab-private `tailscale/policy.hujson`](https://github.com/morey-tech/homelab-private/blob/main/tailscale/policy.hujson). PRs there run validation and post a diff against the live policy; merging to `main` applies it through GitHub Actions. Don't edit the policy in the admin console, because the next merge overwrites it. For this integration, the policy:
   - defines `tag:ocp-gpu-operator`, owned by `autogroup:admin`
   - lets `tag:ocp-gpu-operator` own `tag:ocp-gpu-devspaces`
   - grants `tag:ocp-gpu-devspaces` TCP 443 to `tag:ocp-home-api`, with Kubernetes group `tailnet-admins`

   [tailnet-admins.yaml](../../../ocp-home/system/tailscale/tailnet-admins.yaml) on OCP Home binds `tailnet-admins` to `cluster-admin`.
2. Create a separate OAuth client in the [OAuth console](https://login.tailscale.com/admin/settings/oauth), with **Devices / Core**, **Auth Keys**, and **Services** write scopes, restricted to `tag:ocp-gpu-operator`. The operator can create proxy devices with its owned tag. Configure device approval as appropriate for unattended enrollment.
3. Create a **Login** item named exactly `ocp-gpu-tailscale-operator` in the Bitwarden vault accessible to OCP GPU External Secrets. Store the OAuth client ID as **Username** and client secret as **Password**. [operator-oauth.yaml](operator-oauth.yaml) references that unique item name; renaming it requires updating both remote references. An item UUID can be substituted in both fields if preferred. Do not reuse the OCP Home operator credentials or commit secret values.
4. Ensure Bitwarden's serving cache includes the item. Once Argo has deployed the ExternalSecret, its normal refresh will populate the `operator-oauth` Secret in `tailscale-system`. Missing credentials leave the operator pending until the item becomes available.

The target is `ocp-home-api.taile3c3a8.ts.net`. Both [ocp-home-api.yaml](ocp-home-api.yaml) and the workspace kubeconfig must use that same FQDN. The Service routes to it through Tailscale; the kubeconfig uses it for TLS verification and SNI while connecting to the Kubernetes Service address.

The existing OCP Home policy already grants read-only access to all tagged devices. Grants and Kubernetes RBAC are additive, so the egress device ends up in both `tailnet-readers` and `tailnet-admins`.

## Deploy through Argo CD

```bash
kustomize build --enable-helm kubernetes/ocp-gpu/system/tailscale > /tmp/ocp-gpu-tailscale.yaml
kustomize build kubernetes/ocp-gpu/system/openshift-devspaces > /tmp/ocp-gpu-devspaces.yaml
git diff --check
```

Review, commit, and push the repository changes to `main`. Allow the existing GitOps configuration application to reconcile the [system ApplicationSet](../../openshift-gitops-config/system-appset.yaml), followed by `tailscale-system` and `openshift-devspaces-system`. Do not apply the rendered resources directly.

The ApplicationSet enables server-side apply for the large Tailscale CRDs. It ignores `spec.externalName` only on `tailscale-system/ocp-home-api` and enables `RespectIgnoreDifferences`, because the operator replaces the initial `pending.invalid` value with its generated headless Service. Other Service fields remain managed by Argo.

The SCC binding, NetworkPolicy, and Service admission policy use sync wave `-1`, the operator and ProxyClass use the default wave, and the egress Service uses wave `1`. Wait for credentials and operator readiness before expecting the egress device to appear. The proxy is a single replica; a restart temporarily interrupts access.

After the applications sync, stop/start a Dev Spaces workspace to mount `/etc/ocp-home/kubeconfig`, then follow the [workspace guide](../openshift-devspaces/TAILSCALE.md). The ConfigMap uses `mount-on-start` to avoid restarting active workspaces automatically. The `devspace-homelab` image adds the context to `KUBECONFIG` in shells. No devfile update, browser login, or per-workspace device state is required.

## OpenShift permissions and network access

The pinned operator version is `1.102.4`. Its kernel-mode egress StatefulSet contains a privileged `sysctler` init container and a privileged Tailscale container. [proxy-scc.yaml](proxy-scc.yaml) grants the built-in `privileged` SCC only to `system:serviceaccount:tailscale-system:proxies` using a namespaced RoleBinding. This permission allows those proxy pods privileged access on their worker node. [proxyclass.yaml](proxyclass.yaml) explicitly runs these containers as UID 0. The operator itself remains non-root with dropped capabilities; workspaces receive no new SCC permission.

OAuth credentials and proxy device state stay in Kubernetes Secrets in `tailscale-system`. Preserve these Secrets across restarts to retain device identity. The chart's proxy account has Secret permissions in this namespace, so treat the operator namespace and its privileged proxy pods as trusted infrastructure.

[networkpolicy.yaml](networkpolicy.yaml) selects the operator-generated pods for this specific egress Service. It permits TCP 443 only from pods that have a DevWorkspace ID and run in namespace `admin-devspaces`. The policy matches the namespace on `kubernetes.io/metadata.name`, which the API server sets and namespace owners cannot change. UDP 41641 remains available for authenticated WireGuard transport. Outbound traffic is not restricted, allowing Kubernetes API, DNS, control-plane, DERP, and direct peer connections.

All callers share the proxy's identity. Treat `admin-devspaces` and `tailscale-system` on OCP GPU as holding OCP Home `cluster-admin` credentials.

### Service admission policy

The operator acts on any Service in the cluster that has `tailscale.com/*` metadata or `spec.loadBalancerClass: tailscale`. It creates a tailnet device for that Service, with any tags from `tailscale.com/tags` that the operator owns. Without a guard, any user who can create Services, including every Dev Spaces user in their own namespace, could request their own egress proxy with `tag:ocp-gpu-devspaces`, or expose workloads to the tailnet.

[service-admission-policy.yaml](service-admission-policy.yaml) is a ValidatingAdmissionPolicy with a `Deny` binding. It rejects Service creates and updates outside `tailscale-system` that have:

- any `tailscale.com/` annotation (`tailnet-fqdn`, `tailnet-ip`, `expose`, `tags`, `hostname`, `proxy-class`, `proxy-group`, and so on)
- any `tailscale.com/` label (the operator also reads `tailscale.com/proxy-class` as a label)
- `spec.loadBalancerClass: tailscale`

Services with a `deletionTimestamp` are exempt, so finalizer removal can finish. `failurePolicy: Fail` means that policy errors block the request instead of allowing it. Ingress resources are not covered because the chart's `tailscale` IngressClass is disabled. Connector, ProxyGroup, and other Tailscale custom resources require cluster-level permissions that workspace users do not have.

To add another operator-managed Service, create it in `tailscale-system` through GitOps. Cluster administrators can bypass the policy by working in that namespace, or by editing the policy or binding.

Before this policy was added, no Service outside `tailscale-system` carried Tailscale metadata:

```bash
oc get svc -A -o json | jq -r '.items[]
  | select(.metadata.namespace != "tailscale-system")
  | select(((.metadata.annotations//{})|keys|any(startswith("tailscale.com/")))
      or ((.metadata.labels//{})|keys|any(startswith("tailscale.com/")))
      or .spec.loadBalancerClass == "tailscale")
  | "\(.metadata.namespace)/\(.metadata.name)"'
```

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
oc -n admin-devspaces get configmap ocp-home-kubeconfig
```

The operator should use its ordinary restricted SCC, while the egress pod uses `privileged`. Confirm that the Service's `externalName` now refers to an operator-generated Service and that Argo remains Synced after reconciliation.

Check the Service admission policy with server-side dry runs, which run admission but persist nothing:

```bash
oc get validatingadmissionpolicy,validatingadmissionpolicybinding tailscale-services-operator-namespace-only
oc get validatingadmissionpolicy tailscale-services-operator-namespace-only -o jsonpath='{.status.typeChecking}{"\n"}'

# Denied: Tailscale annotation outside tailscale-system
oc -n admin-devspaces create service clusterip ts-policy-test --tcp=443 --dry-run=client -o yaml \
  | oc annotate --local -f - tailscale.com/tailnet-fqdn=ocp-home-api.taile3c3a8.ts.net -o yaml \
  | oc apply --dry-run=server -f -

# Denied: tailscale loadBalancerClass outside tailscale-system
oc -n admin-devspaces create service loadbalancer ts-policy-test --tcp=443 -o yaml --dry-run=client \
  | oc patch --local -f - --type=merge -p '{"spec":{"loadBalancerClass":"tailscale"}}' -o yaml \
  | oc apply --dry-run=server -f -

# Allowed: ordinary Service, and Tailscale Service in tailscale-system
oc -n admin-devspaces create service clusterip ts-policy-test --tcp=443 --dry-run=server
oc -n tailscale-system create service clusterip ts-policy-test --tcp=443 --dry-run=client -o yaml \
  | oc annotate --local -f - tailscale.com/tailnet-fqdn=example.invalid -o yaml \
  | oc apply --dry-run=server -f -
```

The denied requests should report `ValidatingAdmissionPolicy 'tailscale-services-operator-namespace-only' with binding ... denied request`. `typeChecking` should report no warnings.

From a restarted workspace:

```bash
oc --context=ocp-home-tailnet auth whoami -o json
oc --context=ocp-home-tailnet get pods --all-namespaces
oc --context=ocp-home-tailnet auth can-i '*' '*' --all-namespaces
curl --fail --show-error --noproxy '*' \
  --connect-to ocp-home-api.taile3c3a8.ts.net:443:ocp-home-api.tailscale-system.svc.cluster.local:443 \
  https://ocp-home-api.taile3c3a8.ts.net/version
```

Expect the proxy's FQDN as the username, with `tailnet-admins` and `tailnet-readers` among its groups, and `can-i '*' '*'` to report `yes`. TLS verification must succeed. Repeat after stopping and starting the workspace; authentication should remain automatic.

From an existing pod in any namespace other than `admin-devspaces`, TCP 443 to the egress Service should be blocked. No test pod is deployed by this change.

## Validation performed before deployment

Both Kustomize applications render successfully. Local checks passed for the pinned ProxyClass CRD schema and cluster scope, the proxy-only SCC subject, restricted operator settings, absence of API impersonation permissions and embedded credentials, NetworkPolicy selectors, the rendered ApplicationSet template and drift rules, and matching Service/TLS hostnames. The local `oc` client parses the mounted kubeconfig with an empty user entry. Relative documentation links and `git diff --check` pass.

Read-only cluster inspection confirmed the existing SCC role, workspace labels, GitOps Helm rendering support, and the `openshift-gitops-config` application tracking this path. No resources were applied, no OAuth credentials were created, and no live egress enrollment or authorization checks were performed. Verify admission, network-policy enforcement, TLS/SNI forwarding, and identity/RBAC after your commit and push trigger Argo deployment.

## Troubleshooting and removal

- Operator awaiting its Secret: confirm the Bitwarden item name, vault cache, OAuth scopes, and ExternalSecret conditions without printing credential values.
- Proxy admission failure: inspect pod events, the proxy service account, the SCC RoleBinding, and namespace Pod Security admission. The ApplicationSet labels this namespace for privileged workloads.
- No proxy or pending Service: inspect operator logs, ProxyClass status, OAuth tag ownership, and device approval.
- Service rejected by `tailscale-services-operator-namespace-only`: Tailscale-managed Services belong in `tailscale-system`. If the policy blocks unrelated Services, set the binding's `validationActions` to `[Warn, Audit]` through GitOps while investigating.
- TLS failure: verify both copies of the target FQDN. Do not disable certificate verification.
- API 403, or read-only when admin is expected: check the source proxy tag, the OCP Home destination tag, the `tailnet-admins` capability grant in the tailnet policy, and the `ocp-home-tailnet-admins-cluster-admin` binding on OCP Home.
- Timeout from a workspace: confirm the workspace runs in `admin-devspaces`. Other namespaces are blocked by the NetworkPolicy.
- Rotate credentials through Bitwarden and External Secrets, then arrange an operator rollout through GitOps. Existing proxy state is independent of the OAuth secret.
- To remove access, revoke the egress device or its effective tailnet permissions, remove the workspace ConfigMap and egress Service through GitOps, and let the operator clean up before uninstalling it. Removing only the dedicated grant revokes admin access, but read access remains while the broader `autogroup:tagged` grant applies. Remove the SCC binding when no proxies remain. The ApplicationSet uses `create-update`: deleting the directory alone does not delete its Application.

## References

- [Operator installation and OAuth](https://tailscale.com/docs/kubernetes-operator/install-operator)
- [Egress architecture](https://tailscale.com/docs/kubernetes-operator/egress)
- [Pinned proxy pod template](https://github.com/tailscale/tailscale/blob/v1.102.4/cmd/k8s-operator/deploy/manifests/proxy.yaml)
- [Tagged-device API authentication](https://tailscale.com/docs/kubernetes-operator/api-server-access/auth-and-rbac)
- [OCP Home API configuration](../../../ocp-home/system/tailscale/README.md)
