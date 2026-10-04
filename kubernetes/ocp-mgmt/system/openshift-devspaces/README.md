# OpenShift Dev Spaces on ocp-mgmt

This configuration copies the former [ocp-gpu Dev Spaces setup](../../../ocp-gpu/system/openshift-devspaces/README.md). It migrates configuration; existing workspace PVCs and user data are not transferred.

## Configuration

| Component | Configuration |
|-----------|---------------|
| Operator | `devspaces` Subscription, `stable` channel, automatic install plans in `openshift-operators`; uses the existing global OperatorGroup |
| CheCluster | Open VSX, unlimited workspaces, nested container capabilities disabled for NFS, 2 CPU / 2G memory requests and 4G memory limit |
| Storage | One 5Gi `qnap-nvme` PVC per workspace; persistent user home disabled |
| GitHub OAuth | `github-oauth-config` ExternalSecret from Bitwarden item `4afc34a2-53be-4b9b-b46c-b3a70008d238` via `bitwarden-login` |
| Claude Code | `claude-code-api-key` ClusterExternalSecret injects `ANTHROPIC_API_KEY` into namespaces labelled `app.kubernetes.io/component: workspaces-namespace` |
| Getting started | `morey-tech/homelab` repository sample |

The [NFS configuration](../csi-driver-nfs/README.md) retains workspace data after claim deletion. The requested 5Gi does not impose an NFS directory quota. A StorageClass is explicitly selected because neither management StorageClass is default. Nested container capabilities are disabled: enabling them sets `hostUsers: false`, and the node Linux NFS client does not support the required ID-mapped mount, failing with `mount_setattr /projects: Invalid argument`. Use storage that supports ID-mapped mounts before enabling nested containers. See [Kubernetes user namespace limitations](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/).

## GitHub OAuth callback

The existing Bitwarden item supplies the OAuth client ID and secret. Update that GitHub OAuth App's homepage to [Dev Spaces on ocp-mgmt](https://devspaces.apps.ocp-mgmt.rh-lab.morey.tech) and authorization callback to:

```text
https://devspaces.apps.ocp-mgmt.rh-lab.morey.tech/api/oauth/callback
```

Reusing the app moves its callback away from ocp-gpu. If both installations must authenticate concurrently, create a separate GitHub OAuth App and Bitwarden item, then change both remote references in [github-oauth.yaml](github-oauth.yaml). OpenShift login and public repository access can be validated independently of GitHub OAuth.

See the [Red Hat configuration reference](https://docs.redhat.com/en/documentation/red_hat_openshift_dev_spaces/3.26/html/administration_guide/configuring-devspaces) for storage and OAuth fields.

## Deferred dependencies

- **OCP Home access:** The source `ocp-home-kubeconfig` ConfigMap is omitted because its Tailscale egress Service is not deployed on ocp-mgmt. Migrate Tailscale and its tailnet policy before adding that workspace mount. Workspaces retain their local ocp-mgmt kubeconfig.

## GitOps and verification

The system ApplicationSet explicitly enables `openshift-operators-system` and `openshift-devspaces-system`. Retry and `SkipDryRunOnMissingResource` support installation while operator CRDs become available.

```bash
kustomize build kubernetes/ocp-mgmt/system/openshift-operators
kustomize build kubernetes/ocp-mgmt/system/openshift-devspaces
oc get applications -n openshift-gitops
oc get subscription devspaces -n openshift-operators
oc get csv -n openshift-operators
oc get checluster devspaces -n openshift-devspaces
oc get route devspaces -n openshift-devspaces
oc get externalsecret github-oauth-config -n openshift-devspaces
oc get clusterexternalsecret claude-code-api-key
oc get pvc -n admin-devspaces
```

Open the dashboard through OpenShift OAuth, create a homelab workspace, and verify its PVC uses `qnap-nvme`. Check secret injection without printing credentials.
