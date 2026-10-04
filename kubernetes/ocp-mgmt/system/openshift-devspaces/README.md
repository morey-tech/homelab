# OpenShift Dev Spaces on ocp-mgmt

This configuration copies the former [ocp-gpu Dev Spaces setup](../../../ocp-gpu/system/openshift-devspaces/README.md). It migrates configuration; existing workspace PVCs and user data are not transferred.

## Configuration

| Component | Configuration |
|-----------|---------------|
| Operator | `devspaces` Subscription, `stable` channel, automatic install plans in `openshift-operators`; uses the existing global OperatorGroup |
| CheCluster | Open VSX, unlimited workspaces, nested container capabilities enabled with local XFS storage, 2 CPU / 2G memory requests and 4G memory limit |
| Storage | One 5Gi `lvms-vg-nvme` ReadWriteOnce PVC per workspace; persistent user home disabled |
| GitHub OAuth | `github-oauth-config` ExternalSecret from Bitwarden item `4afc34a2-53be-4b9b-b46c-b3a70008d238` via `bitwarden-login` |
| Claude Code | `claude-code-api-key` ClusterExternalSecret injects `ANTHROPIC_API_KEY` into namespaces labelled `app.kubernetes.io/component: workspaces-namespace` |
| Global VS Code extensions | `openai.chatgpt` via `vscode-editor-configurations` ConfigMap |
| Getting started | `morey-tech/homelab` repository sample |

The [LVM configuration](../openshift-lvm-storage/README.md) provisions XFS volumes from one selected 2 TB Samsung NVMe per eligible node. `disableContainerRunCapabilities: false` enables nested container capabilities and workspace user namespaces. XFS supports the ID-mapped mounts that failed on NFS with `mount_setattr /projects: Invalid argument`; see [Kubernetes user namespace limitations](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/).

The class is explicitly selected and is not the cluster default. Volumes are node-local, use `WaitForFirstConsumer`, and cannot fail over to another node. The operator-generated class uses reclaim policy `Delete`, so deleting a workspace PVC deletes its local data.

## Global VS Code extensions

The [editor ConfigMap](vscode-editor-configurations.yaml) recommends `openai.chatgpt` for all Dev Spaces workspaces. After Argo CD sync, start or restart a workspace and check the editor's Extensions view for installation. Removing Roo Code from the global recommendation list does not uninstall copies already installed in existing workspaces; uninstall those from the Extensions view if needed.

## Existing NFS workspaces

Changing the CheCluster storage class only affects newly created claims; it does not migrate existing `qnap-nvme` PVCs or change their immutable storage class. Stop NFS-backed workspaces and preserve uncommitted files before enabling container-run capabilities globally. Existing NFS workspaces can still fail on ID-mapped mounts after this change.

After LVM storage is ready, recreate disposable workspaces through Dev Spaces so they receive new LVM claims. For workspaces with data to preserve, create a replacement workspace on LVM and restore a backup or copy files before retiring the old workspace. Do not delete the old claims as a migration shortcut. QNAP's `Retain` policy preserves the old backing directories, but Dev Spaces does not attach them to the new LVM claims automatically.

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

The system ApplicationSet explicitly enables `openshift-operators-system`, `openshift-lvm-storage-system`, and `openshift-devspaces-system`. Follow the [storage rollout order](../openshift-lvm-storage/README.md#destructive-initialization-and-argo-cd-rollout) before syncing the Dev Spaces cutover; separate Applications are not readiness-ordered. Retry and `SkipDryRunOnMissingResource` support installation while operator CRDs become available.

```bash
kustomize build kubernetes/ocp-mgmt/system/openshift-lvm-storage
kustomize build kubernetes/ocp-mgmt/system/openshift-operators
kustomize build kubernetes/ocp-mgmt/system/openshift-devspaces
oc get applications -n openshift-gitops
oc get subscription devspaces -n openshift-operators
oc get csv -n openshift-operators
oc get checluster devspaces -n openshift-devspaces
oc get route devspaces -n openshift-devspaces
oc get externalsecret github-oauth-config -n openshift-devspaces
oc get clusterexternalsecret claude-code-api-key
oc get pvc -A
oc get storageclass lvms-vg-nvme -o yaml
```

Open the dashboard through OpenShift OAuth, create a homelab workspace, and verify its new PVC uses `lvms-vg-nvme` and becomes Bound when the workspace starts. Confirm the workspace pod has `spec.hostUsers: false`, then run the following in its terminal:

```bash
findmnt -T /projects -o TARGET,FSTYPE
podman run --rm quay.io/podman/hello
```

Expect XFS backing `/projects` and a successful container run. Stop and restart the workspace and verify a saved file persists. Check secret injection without printing credentials. These runtime checks remain pending until the user deploys through Argo CD.
