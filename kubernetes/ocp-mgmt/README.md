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

Dev Spaces is enabled for cloud development. Local/block storage, GPU/NFD operators, virtualization, ACM, Tailscale, AAP, and other applications are deferred. Certificate automation is enabled as the first migration stage after bootstrap. This bootstrap does not change node roles, labels, taints, disks, or machine configuration.

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

Core bootstrap Applications: `openshift-gitops-config`, `external-secrets-system`, and `htpass-admin-system`. The certificate migration adds `cert-manager-operator-system`, `cert-manager-system`, `openshift-ingress-system`, and `openshift-apiserver-system`. Discord alerting adds `openshift-monitoring-system`, NFS provisioning adds `csi-driver-nfs-system`, and Dev Spaces adds `openshift-operators-system` and `openshift-devspaces-system`. Sign in to Argo CD through OpenShift OAuth as `admin`.

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

## Application Catalog

| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| OpenShift Dev Spaces | openshift-devspaces | [devspaces.apps.ocp-mgmt.rh-lab.morey.tech](https://devspaces.apps.ocp-mgmt.rh-lab.morey.tech) | Cloud development environments | Per-workspace QNAP NVMe storage, Open VSX, Bitwarden-backed credentials, Roo Code |

See [Dev Spaces configuration](system/openshift-devspaces/README.md) for verification, the required GitHub OAuth callback update, and deferred Tailscale/inference dependencies.

## Staged Migration

The system ApplicationSet explicitly includes ESO, administrator authentication, cert-manager and its operator, API/ingress certificates, Discord alerting, the NFS CSI driver, the Dev Spaces operator, and Dev Spaces configuration. New system components require an explicit directory entry in `openshift-gitops-config/system-appset.yaml`. The application ApplicationSet and old application manifests have been removed; add application discovery when the first workload is ready to migrate.

Use the retained [ocp-gpu configuration](../ocp-gpu/README.md) as migration source material. Review each component's hostnames, namespaces, storage, secrets, and node placement before enabling it. Old management manifests remain available in Git history.

## Related Documentation

- [Kubernetes GitOps workflow](../README.md)
- [External Secrets setup](system/external-secrets/README.md)
- [Administrator authentication](system/htpass-admin/README.md)
