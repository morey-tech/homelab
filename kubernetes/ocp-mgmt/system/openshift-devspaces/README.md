# OpenShift Dev Spaces on ocp-mgmt

This configuration copies the former [ocp-gpu Dev Spaces setup](../../../ocp-gpu/system/openshift-devspaces/README.md). It migrates configuration; existing workspace PVCs and user data are not transferred.

## Configuration

| Component | Configuration |
|-----------|---------------|
| Operator | `devspaces` Subscription, `stable` channel, automatic install plans in `openshift-operators`; uses the existing global OperatorGroup |
| CheCluster | Open VSX, unlimited workspaces, nested container capabilities enabled with local XFS storage, 2 CPU / 2G memory requests and 4G memory limit |
| Storage | One 5Gi `lvms-vg-nvme` ReadWriteOnce PVC per workspace; persistent user home disabled |
| GitHub OAuth | `github-oauth-config` ExternalSecret from Bitwarden item `4afc34a2-53be-4b9b-b46c-b3a70008d238` via `bitwarden-login` |
| Claude Code / direct Anthropic | `claude-code-api-key` ClusterExternalSecret injects the shared `ANTHROPIC_API_KEY` into namespaces labelled `app.kubernetes.io/component: workspaces-namespace` |
| OpenCode MaaS | `maas-api-key` ExternalSecret reads the automatically rotated in-cluster key; Dev Spaces synchronizes `MAAS_API_KEY` to user namespaces |
| Global VS Code extensions | `openai.chatgpt` and `sst-dev.opencode` via `vscode-editor-configurations` ConfigMap |
| Getting started | `morey-tech/homelab` repository sample |

The [LVM configuration](../openshift-lvm-storage/README.md) provisions XFS volumes from one selected 2 TB Samsung NVMe per eligible node. `disableContainerRunCapabilities: false` enables nested container capabilities and workspace user namespaces. XFS supports the ID-mapped mounts that failed on NFS with `mount_setattr /projects: Invalid argument`; see [Kubernetes user namespace limitations](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/).

The class is explicitly selected and is not the cluster default. Volumes are node-local, use `WaitForFirstConsumer`, and cannot fail over to another node. The operator-generated class uses reclaim policy `Delete`, so deleting a workspace PVC deletes its local data.

## Global VS Code extensions

The [editor ConfigMap](vscode-editor-configurations.yaml) recommends `openai.chatgpt` and [OpenCode (`sst-dev.opencode`)](https://open-vsx.org/extension/sst-dev/opencode) for all Dev Spaces workspaces. OpenCode's extension uses the CLI supplied by `devspace-base`; custom images must also provide the CLI. After Argo CD sync, start or restart a workspace and check the editor's Extensions view for installation. Removing Roo Code from the global recommendation list does not uninstall copies already installed in existing workspaces; uninstall those from the Extensions view if needed.

## OpenCode

The `devspace-base` image provides the OpenCode terminal CLI, inherited by `devspace-homelab`, following the [Red Hat Dev Spaces integration](https://developers.redhat.com/articles/2026/04/22/opencode-model-neutral-ai-coding-assistant-openshift-dev-spaces). Neither image contains provider settings. The platform's [OpenCode ConfigMaps](opencode-config.yaml) use the `workspaces-config` labels to synchronize into every user namespace. They mount configuration at `/etc/devspaces/opencode` and inject `OPENCODE_CONFIG=/etc/devspaces/opencode/opencode-maas.json`, independent of repository and container home directory. They follow the existing mount-on-start pattern; restart workspaces after reconciliation to receive updates.

The managed `maas-api-key` Secret supplies `MAAS_API_KEY` as an environment variable. The configuration resolves it at runtime; users do not need `/connect`, key creation, or terminal exports. The existing `claude-code-api-key` Secret still supplies `ANTHROPIC_API_KEY` for Claude Code and the optional direct profile. Custom workspace images receive configuration but must provide their own OpenCode binary.

The default model is `maas-anthropic/claude-sonnet-4-6`. Claude and local Qwen are enabled through MaaS, session sharing and self-updates are disabled, and tools require approval. These are [OpenCode configuration](https://opencode.ai/docs/config/) defaults, not an enforced security boundary: project/user settings can override them. Repository `AGENTS.md` instructions still apply, including commit review and GitOps deployment rules.

Roll out the image changes first: after review and push, wait for `Container Build` to publish both `devspace-base` and its rebuilt `devspace-homelab` consumer. Then commit/push the reviewed platform defaults and let Argo CD reconcile them. This prevents new fallback workspaces from starting with the older image before OpenCode is available. The workflow publishes `latest` and immutable `sha-...` tags. Create a new workspace, or update an existing workspace's devfile through the dashboard to include the `opencode-data` volume and select the published image SHA tag. A Git pull alone does not update an existing workspace's pod template. Do not delete an existing workspace PVC to upgrade it.

In the new workspace terminal:

```bash
opencode --version
test -n "${MAAS_API_KEY:-}" && printf 'MaaS key is present\n'
test -r "$OPENCODE_CONFIG" && printf 'Platform configuration is mounted\n'
cd /projects/homelab
opencode models maas-anthropic
opencode models maas-local
opencode
```

Ask for a short greeting without tools to verify API access (billed to the existing Anthropic account). Do not print the key or dump resolved provider configuration. Select models with `/models`. The devfile persists OpenCode's data directory at `~/.local/share/opencode`, including sessions, on the workspace PVC; deleting that PVC deletes this data. Verify a session survives a workspace stop/start. Caches and UI state outside the data directory are ephemeral. Secret rotation requires a workspace restart to refresh the injected environment.

## MaaS model selection

The default profile `/etc/devspaces/opencode/opencode-maas.json` connects to [OpenShift AI Models-as-a-Service](../redhat-ods-operator/maas/README.md). After platform bootstrap and Secret synchronization, a new workspace can run `opencode` immediately.

The [key rotator](../redhat-ods-operator/maas/key-rotation/README.md) requests 90-day keys for the shared `devspaces-workspaces` subscription and renews when 30 days remain. An ExternalSecret reads the current key from `devspaces-maas/maas-workspace-key` into `openshift-devspaces/maas-api-key`. Dev Spaces' native `workspaces-config` synchronization copies it to user namespaces during provisioning and on updates. Only the key is injected; rotation metadata stays in the source namespace. No Bitwarden item or manually maintained bootstrap token is needed.

The Secret uses `mount-on-start: true`: rotation updates stored credentials without restarting active workspaces. Existing processes retain their previous key until the workspace is stopped and started. Old keys keep their original expiry, so sessions may eventually receive 401; restart the workspace to load the current key. A workspace started late in a key's lifetime does not get a fresh 90 days of validity. All workspaces share the service account identity and subscription quota, rather than individual user attribution.

For initial rollout, deploy the rotator first and wait for the source Secret, then deploy these defaults. Before opening workspaces, check:

```bash
oc get cronjob,jobs -n devspaces-maas
oc get clustersecretstore devspaces-maas
oc get externalsecret maas-api-key -n openshift-devspaces
oc get secret maas-api-key -n openshift-devspaces
```

Wait for the ExternalSecret's `Ready=True` condition. Existing workspaces need one stop/start to adopt the new default profile and environment. Custom images still need the OpenCode CLI.

In `/models`, select **Qwen3 4B Instruct (local, MaaS)** or **Claude Sonnet 4.6 (MaaS)**. Claude is the profile's initial model. Qwen uses OpenAI Chat Completions; Claude uses native Anthropic Messages to preserve streaming. The Claude provider explicitly sends `Authorization: Bearer` because MaaS does not accept the Anthropic SDK's `x-api-key` header for client authentication. Both use `https://maas.apps.ocp-mgmt.rh-lab.morey.tech/v1` and the same MaaS key. This selects the requested model explicitly; it does not provide automatic fallback. The local model's context window is 32,768 tokens, so start a fresh session if a Claude conversation is too large.

Native Anthropic passthrough is not subject to MaaS token metering in this preview; retain spending limits at Anthropic. See the platform guide for post-deployment streaming, tool-call, authentication, and large-request checks.

The direct Anthropic profile is still available explicitly:

```bash
OPENCODE_CONFIG=/etc/devspaces/opencode/opencode.json opencode
```

## Default workspace components

The [CheCluster](checluster.yaml) defines `spec.devEnvironments.defaultComponents`: the homelab tools container and its persistent OpenCode data volume. This is the platform fallback for repositories without devfile components, including repositories without a devfile. It is not a complete default devfile with commands and events, and does not override repositories that define their own components. See the [CheCluster reference](https://docs.redhat.com/en/documentation/red_hat_openshift_dev_spaces/3.26/pdf/administration_guide/Red_Hat_OpenShift_Dev_Spaces-3.26-Administration_guide-en-US.pdf).

The fallback deliberately has no homelab-specific post-start commands. Repositories with their own devfiles can use a `devspace-base` derivative and declare persistence themselves, as [this repository does](../../../../devfile.yaml). Match the volume mount to that image's home directory (`/home/user` in the base image, `/home/morey-tech` in the homelab image). Changing these defaults affects newly generated workspaces, not existing workspace definitions. After rollout, create a workspace from a repository without a devfile and verify the selected image, OpenCode config/key availability, and session persistence across stop/start.

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

## OCP Home access through Tailscale

The [Tailscale application](../tailscale/README.md) provides an egress proxy to OCP Home using the existing OCP GPU OAuth client and tags, with management-specific device hostnames. The [workspace kubeconfig](ocp-home-kubeconfig.yaml) mounts at `/etc/ocp-home/kubeconfig` when a workspace starts. The homelab image merges it into `KUBECONFIG` through shell initialization, preserving the local ocp-mgmt context as the default.

Only DevWorkspace pods in `admin-devspaces` can reach the proxy, whose shared tailnet identity has `cluster-admin` on OCP Home through the existing grant. Other user namespaces receive the kubeconfig but cannot connect. See [workspace setup and verification](TAILSCALE.md); stop/start existing workspaces after Argo sync to receive the mount.

## GitOps and verification

The system ApplicationSet explicitly enables `openshift-operators-system`, `openshift-lvm-storage-system`, `openshift-devspaces-system`, and `tailscale-system`. Follow the [storage rollout order](../openshift-lvm-storage/README.md#destructive-initialization-and-argo-cd-rollout) before syncing the Dev Spaces cutover; separate Applications are not readiness-ordered. Retry and `SkipDryRunOnMissingResource` support installation while operator CRDs become available.

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
