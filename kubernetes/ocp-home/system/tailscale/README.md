# Tailscale-authenticated OCP Home API

The operator exposes a private HTTPS API endpoint with hostname `ocp-home-api` in the tailnet's MagicDNS domain. The full domain is assigned by Tailscale at enrollment; use the discovery command below instead of guessing it. The native endpoint remains `https://api.ocp-home.rh-lab.morey.tech:6443`.

## Installation and enrollment

ArgoCD's system ApplicationSet discovers this directory as `tailscale-system`. Kustomize installs the pinned Tailscale operator chart in namespace `tailscale-system`; the ApplicationSet enables server-side apply for its large CRDs.

1. Merge the entries in [tailnet-policy.json](tailnet-policy.json) into the existing policy in the [Tailscale access controls console](https://login.tailscale.com/admin/acls). Preserve existing entries and grants. This file is an additive policy fragment, not a replacement for the tailnet policy, and is not applied by ArgoCD.
2. Enable MagicDNS and HTTPS certificates in the [DNS console](https://login.tailscale.com/admin/dns). HTTPS certificate issuance publishes the endpoint hostname in certificate transparency logs; the endpoint itself remains private.
3. In the [OAuth clients console](https://login.tailscale.com/admin/settings/oauth), create an operator client with **Devices / Core**, **Auth Keys**, and **Services** write scopes, restricted to `tag:ocp-home-api`. The policy lets that tag own `tag:ocp-home-proxy` for operator-managed proxies. Approve the operator device if tailnet device approval requires it.
4. In the Bitwarden vault used by OCP Home's External Secrets service, use the **Login** item `ocp-home Tailscale operator` (UUID `4e619a2e-c27e-483e-943f-b4d000f315a9`). Store the OAuth client ID as **Username** and client secret as **Password**. [operator-oauth.yaml](operator-oauth.yaml) references the UUID, so renaming the item does not affect synchronization. Do not commit credentials or pass them as Helm values.
5. Sync Bitwarden's local vault cache and request a secret refresh:

```bash
oc -n external-secrets-system exec deployment/bitwarden-cli -- bw sync
oc -n tailscale-system annotate externalsecret operator-oauth force-sync="$(date +%s)" --overwrite
oc -n tailscale-system wait externalsecret/operator-oauth --for=condition=Ready --timeout=120s
oc -n tailscale-system rollout status deployment/operator --timeout=180s
```

The operator reads `operator-oauth` keys `client_id` and `client_secret`. Its separate `operator` Secret stores device state; preserve it across upgrades to retain enrollment and hostname. After rotating OAuth credentials, sync External Secrets and restart the deployment.

Validate the manifests locally before committing and pushing:

```bash
kustomize build --enable-helm kubernetes/ocp-home/system/tailscale > /tmp/ocp-home-tailscale.yaml
```

Deploy through ArgoCD after committing and pushing the configuration to its tracked revision. Do not apply the rendered manifests directly. Run the secret refresh and rollout checks above after ArgoCD has created the resources.

The operator uses userspace networking for its in-process API proxy, with an OpenShift-assigned non-root UID, dropped capabilities, and no privileged SCC binding. General ingress/egress proxies are outside this configuration's scope. Tailscale's documented OpenShift support limitations make live admission and runtime checks necessary.

## Policy and RBAC

`apiServerProxyConfig.mode: "true"` enables Tailscale identity authentication and chart-managed impersonation permissions. The policy allows TCP 443 to `tag:ocp-home-api` from both `autogroup:member` (tailnet users) and `autogroup:tagged` (all tagged devices), and maps both to `tailnet-readers`. The dedicated destination tag keeps this grant specific to OCP Home.

[tailnet-readers.yaml](tailnet-readers.yaml) binds that group to the built-in `view` ClusterRole across namespaces. User devices retain the user's Tailscale login as their Kubernetes username; tagged devices use their node FQDN. Do not bind `system:authenticated` or assign `system:masters` for this setup. Existing RBAC and other tailnet grants are additive, so inspect them when checking effective permissions.

## Client setup and validation

Run on a device already connected to this tailnet with Tailscale and kubectl installed. Discover the actual endpoint:

```bash
PROXY_FQDN=$(tailscale status --json | jq -er '[.Peer[] | select(.HostName == "ocp-home-api") | .DNSName | rtrimstr(".")] | if length == 1 then .[0] else error("expected one ocp-home-api peer") end')
printf 'https://%s\n' "$PROXY_FQDN"
tailscale configure kubeconfig "$PROXY_FQDN"
kubectl auth whoami
kubectl get pods --all-namespaces
```

For acceptance testing, use a fresh temporary kubeconfig to demonstrate that no OpenShift token or existing client credentials are involved. Run the following in a subshell so the normal kubeconfig remains selected afterward:

```bash
(
  export KUBECONFIG=$(mktemp)
  trap 'rm -f "$KUBECONFIG"' EXIT
  tailscale configure kubeconfig "$PROXY_FQDN"
  kubectl config view --minify
  kubectl auth whoami -o json
  kubectl get pods --all-namespaces
  kubectl auth can-i list pods --all-namespaces
  kubectl auth can-i get secrets --all-namespaces
  kubectl auth can-i create deployments --all-namespaces
  curl --fail --show-error "https://${PROXY_FQDN}/version"
)
```

Expected: whoami reports the caller's login or tagged node FQDN and includes `tailnet-readers`; pod listing and `can-i list pods` succeed. Secret reads and deployment creation should return `no` unless another existing grant independently grants more access. Curl must validate TLS without `--insecure`. Repeat from both a user-owned device and a tagged device. The client must reach the endpoint through Tailscale to supply its identity; shared LAN connectivity alone is insufficient.

Verify the original admin context still works separately:

```bash
oc whoami --show-server
oc whoami
oc get --raw=/readyz
oc get pods --all-namespaces
oc -n tailscale-system get externalsecret,pods
oc -n tailscale-system logs deployment/operator --tail=60
```

## Troubleshooting and rollback

- Missing `operator-oauth`: verify the Bitwarden item name/UUID and properties, sync its cache, and inspect ExternalSecret conditions. Never print the Secret's values.
- Enrollment errors: verify OAuth scopes and tag ownership, device approval, and outbound access to the Tailscale control plane.
- TLS errors: verify MagicDNS, HTTPS enablement, and the actual enrolled FQDN. Resolve a hostname collision rather than disabling TLS verification.
- HTTP 403: inspect `kubectl auth whoami`, the app capability grant, and the group binding. A network-only grant does not assign the reader group.
- Admission errors: inspect pod events and SCC selection before changing security permissions.
- Rollback: disable automatic sync for `tailscale-system`, scale `deployment/operator` to zero, and remove this endpoint's tailnet grant. Revert the GitOps addition and remove its resources deliberately. The ApplicationSet uses `create-update`, so removing the directory alone does not delete the Application. Native API authentication is independent and remains available.

## References

- [API proxy setup](https://tailscale.com/docs/kubernetes-operator/api-server-access/setup-api-over-tailscale)
- [Identity mapping and RBAC](https://tailscale.com/docs/kubernetes-operator/api-server-access/auth-and-rbac)
- [Grant syntax](https://tailscale.com/docs/reference/syntax/grants)
- [Operator installation and limitations](https://tailscale.com/docs/features/kubernetes-operator)
