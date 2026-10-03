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

No application workloads are enabled. Storage, GPU/NFD operators, certificates, custom ingress, virtualization, ACM, DevSpaces, Tailscale, AAP, and other applications are deferred. The cluster uses its default ingress certificate. This bootstrap does not change node roles, labels, taints, disks, or machine configuration.

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

Expected Applications: `openshift-gitops-config`, `external-secrets-system`, and `htpass-admin-system`. Sign in to Argo CD through OpenShift OAuth as `admin`.

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

## Staged Migration

The system ApplicationSet explicitly includes only `system/external-secrets` and `system/htpass-admin`. New system components require an explicit directory entry in `openshift-gitops-config/system-appset.yaml`. The application ApplicationSet and old application manifests have been removed; add application discovery when the first workload is ready to migrate.

Use the retained [ocp-gpu configuration](../ocp-gpu/README.md) as migration source material. Review each component's hostnames, namespaces, storage, secrets, and node placement before enabling it. Old management manifests remain available in Git history.

## Related Documentation

- [Kubernetes GitOps workflow](../README.md)
- [External Secrets setup](system/external-secrets/README.md)
- [Administrator authentication](system/htpass-admin/README.md)
