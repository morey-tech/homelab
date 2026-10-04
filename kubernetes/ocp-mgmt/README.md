# OpenShift Cluster: ocp-mgmt

Recreated management cluster with a minimal GitOps foundation. Workloads from the former `ocp-gpu` cluster will migrate in stages.

## Cluster Information

| Node | Role |
|------|------|
| ms-02 | Control plane and worker |
| ms-03 | Control plane and worker |
| ms-04 | Control plane and worker |
| tr-gpu | Dedicated worker; formerly the ocp-gpu node |

- **API**: [api.ocp-mgmt.rh-lab.morey.tech:6443](https://api.ocp-mgmt.rh-lab.morey.tech:6443)
- **Console**: [console-openshift-console.apps.ocp-mgmt.rh-lab.morey.tech](https://console-openshift-console.apps.ocp-mgmt.rh-lab.morey.tech)
- **Argo CD**: [cluster-argocd-server-openshift-gitops.apps.ocp-mgmt.rh-lab.morey.tech](https://cluster-argocd-server-openshift-gitops.apps.ocp-mgmt.rh-lab.morey.tech)

## Bootstrap Scope

- **OpenShift GitOps**: Operator, `cluster-argocd` instance, controller permissions, and root Application adapted from `ocp-gpu`.
- **External Secrets Operator**: Bitwarden CLI backend and the `bitwarden-login`, `bitwarden-fields`, and `bitwarden-notes` ClusterSecretStores.
- **Administrator access**: HTPasswd `admin` user, `cluster-admins` group, OpenShift OAuth for Argo CD, and an `ocp-mgmt` console banner.

Dev Spaces uses local NVMe LVM storage for cloud development with nested containers. GPU/NFD operators are enabled for the migrated GPU worker; virtualization, ACM, AAP, and other applications are deferred. Certificate automation is enabled as the first migration stage after bootstrap. This bootstrap does not change node roles, labels, taints, disks, or machine configuration.

## Initial Setup

Run commands from the repository root. Install `oc`, Helm 3, and `htpasswd`. The script uses `oc kustomize --enable-helm` and needs network access to the ESO chart repository and container registries.

**Merge the minimal configuration before running bootstrap.** The root Application and ApplicationSet track the repository's default branch (`HEAD`). Running against an older default branch would reconcile the previous management configuration.

### Log In to the New Cluster

Use the installer-provided administrator credentials:

```bash
oc login --server=https://api.ocp-mgmt.rh-lab.morey.tech:6443
oc get nodes
```

Confirm `ms-02`, `ms-03`, `ms-04`, and `tr-gpu` are Ready. The bootstrap script refuses to run against another API endpoint.

### Prepare Bitwarden Credentials

Copy the Notes section of the `ocp-mgmt.rh-lab.morey.tech external-secrets bitwarden` entry in Bitwarden into `kubernetes/ocp-mgmt/system/external-secrets/bitwarden-secret.yaml`. It must define the `bitwarden-cli` Secret in `external-secrets-system`, with `BW_PASSWORD`, `BW_CLIENTID`, and `BW_CLIENTSECRET` keys. This file is Git-ignored; verify any existing local copy still has the intended credentials.

### Set Up HTPasswd Auth

Create the `admin` password file if needed:

```bash
htpasswd -B -c kubernetes/ocp-mgmt/ocp-mgmt.htpasswd admin
# Enter password from Bitwarden: "OpenShift ocp-mgmt admin password"
```

The password file is Git-ignored. The script creates or updates `htpass-secret`, applies the HTPasswd identity provider, and grants `admin` cluster access through `cluster-admins`.

### Run Bootstrap

```bash
bash kubernetes/ocp-mgmt/bootstrap/bootstrap.sh
```

The script checks credentials and renders manifests before changing the cluster. It installs ESO before applying ClusterSecretStores, waits for operator and Argo CD readiness, then enables the two system Applications. It can be rerun after resolving a failure. Override `HTPASSWD_FILE` or `BITWARDEN_SECRET_FILE` with absolute paths if credentials are stored elsewhere.

### Verify Access and GitOps

```bash
oc login -u admin --server=https://api.ocp-mgmt.rh-lab.morey.tech:6443
oc auth can-i '*' '*' --all-namespaces
oc get applications -n openshift-gitops
oc get clustersecretstores
oc get pods -n external-secrets-system
oc get route cluster-argocd-server -n openshift-gitops
```

Core bootstrap Applications: `openshift-gitops-config`, `external-secrets-system`, and `htpass-admin-system`. The certificate migration adds `cert-manager-operator-system`, `cert-manager-system`, `openshift-ingress-system`, and `openshift-apiserver-system`. Discord alerting adds `openshift-monitoring-system`, NFS provisioning adds `csi-driver-nfs-system`, and Dev Spaces adds `openshift-operators-system` and `openshift-devspaces-system`; Tailscale egress adds `tailscale-system`. Sign in to Argo CD through OpenShift OAuth as `admin`.

The script retains `kubeadmin`. After confirming `admin` login and cluster-admin access, remove the installer account manually:

```bash
oc delete secret kubeadmin -n kube-system
```

### Manual Authentication Recovery

To reapply the HTPasswd configuration independently:

```bash
oc create secret generic htpass-secret \
  --from-file=htpasswd=kubernetes/ocp-mgmt/ocp-mgmt.htpasswd \
  -n openshift-config --dry-run=client -o yaml | oc apply -f -
oc apply -k kubernetes/ocp-mgmt/system/htpass-admin
```

## Certificate Management

The configuration copies the former `ocp-gpu` setup with `ocp-mgmt` hostnames and ACME contact email:

- **Red Hat cert-manager Operator**: `stable-v1` channel in `cert-manager-operator`; manages cert-manager in `cert-manager`.
- **OpenShift Route support**: `openshift-routes` chart `v0.8.5` for annotated Routes.
- **Cloudflare DNS-01**: ESO obtains `cloudflare-api-token-secret` from the existing Bitwarden login item. The token remains outside Git.
- **ClusterIssuers**: `letsencrypt-staging` and `letsencrypt-prod`, with public DNS resolvers `8.8.8.8:53` and `1.1.1.1:53`.
- **Ingress**: `apps-wildcard-cert` covers `apps.ocp-mgmt.rh-lab.morey.tech` and `*.apps.ocp-mgmt.rh-lab.morey.tech`.
- **API**: `api-server-cert` covers `api.ocp-mgmt.rh-lab.morey.tech`.

Certificates use the production issuer. Argo CD sync wave 1 issues each certificate before wave 2 changes the IngressController or APIServer certificate reference. These components are explicitly enabled by `openshift-gitops-config/system-appset.yaml`; the initial bootstrap script remains unchanged.

```bash
oc get applications -n openshift-gitops
oc get csv -n cert-manager-operator
oc get pods -n cert-manager
oc get externalsecret cloudflare-api-token-secret -n cert-manager
oc get clusterissuers
oc get certificate apps-wildcard-cert -n openshift-ingress
oc get certificate api-server-cert -n openshift-config
oc get clusteroperators authentication ingress kube-apiserver
```

For local rendering, use a standalone Kustomize version with OCI Helm support (Argo CD uses v5.8.1):

```bash
kustomize build --enable-helm kubernetes/ocp-mgmt/system/cert-manager-operator
kustomize build kubernetes/ocp-mgmt/system/cert-manager
```

## Discord Alert Notifications

The platform Alertmanager sends warning and critical alerts, plus resolved notifications, to Discord. Notification titles identify `ocp-mgmt`. Informational alerts and Watchdog remain on empty receivers. Existing severity inhibition rules, namespace grouping, 30-second initial wait, 5-minute group interval, 12-hour repeat interval, and environment proxy settings are preserved.

ESO reads the webhook URL from the **password** field of Bitwarden item `7c74654f-a595-4aa6-a1c4-b4d80182f0cd`. It renders the existing `openshift-monitoring/alertmanager-main` Secret through [the monitoring component](system/openshift-monitoring/alertmanager-external-secret.yaml). The URL is not committed to Git. `creationPolicy: Merge` and `deletionPolicy: Retain` preserve the platform Secret's lifecycle. Alertmanager reloads configuration automatically.

```bash
oc get application openshift-monitoring-system -n openshift-gitops
oc get externalsecret alertmanager-main -n openshift-monitoring
oc get pods -n openshift-monitoring -l alertmanager=main
oc get clusteroperator monitoring
```

To rotate the webhook, update the same Bitwarden password and refresh ESO after the Bitwarden CLI backend has synchronized:

```bash
oc annotate externalsecret alertmanager-main -n openshift-monitoring \
  force-sync="$(date +%s)" --overwrite
```

Make routing changes in Git; direct edits to `alertmanager-main` will be overwritten by ESO. Removing the ExternalSecret leaves the last configuration in place, so disable the Discord receivers in Git before removing the integration.

## NFS Storage

The non-default `qnap-nvme` and `qnap-mass` StorageClasses dynamically provision per-PVC directories on `qnap-01.rh-lab.morey.tech:/storage-nvme` and `/storage-mass`, respectively. Both use the same `ocp-mgmt/` subdirectory layout beneath their export. They support `ReadWriteMany` across all four nodes and retain data when claims are deleted. Select `storageClassName: qnap-nvme` or `storageClassName: qnap-mass` in workload PVCs. Requested PVC sizes do not enforce directory quotas on NFS.

See [QNAP NFS storage](system/csi-driver-nfs/README.md) for export prerequisites, an example claim, and operational details.

## Local NVMe LVM Storage

[Red Hat LVM Storage](system/openshift-lvm-storage/README.md) provides the non-default `lvms-vg-nvme` class with XFS on one 2 TB Samsung drive each on `ms-02`, `ms-04`, and `tr-gpu`. The second `tr-gpu` drive, WD SN750 serial `20530C800438`, provides the separate non-default `lvms-vg-ai` class for model storage, datasets, caches, and other local workloads. All disks use serial-specific selection; OS disks are excluded. `ms-03` is excluded until a 2 TB drive is installed and explicitly selected.

Dev Spaces uses this class to support workspace user namespaces and nested containers. Volumes are node-local and not replicated. Initial sync enables authorized wiping of legacy data on the selected drives; review the storage README for the shared old tr-gpu pool, rollout order, and required disk readiness checks. Existing NFS workspace claims require separate recreation or migration.

## NVIDIA GPU Support

- **OpenShift NFD**: [Node Feature Discovery](system/openshift-nfd) labels node hardware, including NVIDIA PCI devices, in `openshift-nfd`.
- **NVIDIA GPU Operator**: [Operator and ClusterPolicy](system/nvidia-gpu-operator) install drivers, the container toolkit, GPU device plugin, and DCGM monitoring in `nvidia-gpu-operator`. The console dashboard remains in `openshift-config-managed`.

Both operators retain the `stable` channel and automatic install plan approval from `ocp-gpu`. The ClusterPolicy retains CRI-O, the OpenShift Driver Toolkit, automatic driver upgrades, and the existing MIG settings. GPU workloads request `nvidia.com/gpu`; application workloads are migrated separately.

After GitOps sync, verify hardware discovery and GPU capacity on `tr-gpu`:

```bash
oc get applications openshift-nfd-system nvidia-gpu-operator-system -n openshift-gitops
oc get csv -n openshift-nfd
oc get nodefeaturediscovery nfd-instance -n openshift-nfd
oc get pods -n openshift-nfd
oc get csv -n nvidia-gpu-operator
oc get clusterpolicy gpu-cluster-policy
oc get pods -n nvidia-gpu-operator
oc get nodes -l feature.node.kubernetes.io/pci-10de.present=true
oc get node tr-gpu -o jsonpath='{.status.allocatable.nvidia\.com/gpu}{"\n"}'
```

The manifests were moved out of the retired `ocp-gpu` cluster. That cluster is no longer running, and its former node, `tr-gpu`, now belongs to `ocp-mgmt`. There are no running deployments on `ocp-gpu` to preserve or uninstall.

## OpenShift AI

[OpenShift AI](system/redhat-ods-operator/README.md) provides its dashboard and KServe for model serving on `tr-gpu`. The operator tracks `stable-3.5` with manual InstallPlan approval. Training, pipelines, workbenches, and distributed inference components are disabled. Model data uses the separate `lvms-vg-ai` storage class.

[The inference server](applications/inference-server/README.md) initially serves Qwen3-0.6B as `local-llm` using the NVIDIA vLLM runtime managed by KServe. It uses one GPU, a persistent model volume on the WD NVMe, HTTPS token authentication, and a recreate update strategy. Its manifests and model revision are managed in Git.

## Application Catalog

| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| OpenShift Dev Spaces | openshift-devspaces | [devspaces.apps.ocp-mgmt.rh-lab.morey.tech](https://devspaces.apps.ocp-mgmt.rh-lab.morey.tech) | Cloud development environments | Per-workspace local NVMe LVM storage, nested containers, Open VSX, Bitwarden-backed credentials |
| OpenShift AI | redhat-ods-applications | [OpenShift AI dashboard](https://rhods-dashboard-redhat-ods-applications.apps.ocp-mgmt.rh-lab.morey.tech) | Model deployment and monitoring | KServe, RTX 3090 hardware profile, OpenShift authentication |
| Inference Server | inference-server | [API access](applications/inference-server/README.md#clients) | OpenAI-compatible chat inference | KServe-managed vLLM, Qwen3-0.6B, dedicated NVMe model storage, token authentication |
| AnythingLLM | anythingllm | [anythingllm.apps.ocp-mgmt.rh-lab.morey.tech](https://anythingllm.apps.ocp-mgmt.rh-lab.morey.tech) | Chat and document workspaces using `local-llm` | Generated UI password, scoped KServe credential, native embeddings, persistent AI NVMe storage |

See [Dev Spaces configuration](system/openshift-devspaces/README.md) for verification, the required GitHub OAuth callback update, and [Tailscale access to OCP Home](system/openshift-devspaces/TAILSCALE.md).

## Tailscale

- [Tailscale operator and egress proxy](system/tailscale/README.md): connects admin Dev Spaces workspaces to the OCP Home API. Reuses the OCP GPU OAuth client and tags with distinct management device hostnames, a proxy-only privileged SCC binding, and network and Service admission policies.

## Staged Migration

The system ApplicationSet explicitly includes ESO, administrator authentication, cert-manager and its operator, API/ingress certificates, Discord alerting, the NFS CSI driver, LVM Storage, the Dev Spaces operator, Dev Spaces configuration, Tailscale egress, OpenShift NFD, the NVIDIA GPU Operator, and OpenShift AI. New system components require an explicit directory entry in `openshift-gitops-config/system-appset.yaml`. The application ApplicationSet explicitly includes `applications/inference-server` and [AnythingLLM](applications/anythingllm/README.md); add other workloads deliberately as they migrate.

Use the retained [ocp-gpu configuration](../ocp-gpu/README.md) as migration source material. Review each component's hostnames, namespaces, storage, secrets, and node placement before enabling it. Old management manifests remain available in Git history.

## Related Documentation

- [Kubernetes GitOps workflow](../README.md)
- [External Secrets setup](system/external-secrets/README.md)
- [Administrator authentication](system/htpass-admin/README.md)
