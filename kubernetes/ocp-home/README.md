# OpenShift Cluster: ocp-home

Production cluster hosting personal applications with hardware GPU acceleration (Intel i915).

## Cluster Information

- **API Endpoint**: `https://api.ocp-home.rh-lab.morey.tech:6443`
- **Console**: `https://console-openshift-console.apps.ocp-home.rh-lab.morey.tech`
- **ArgoCD**: `https://openshift-gitops-server-openshift-gitops.apps.ocp-home.rh-lab.morey.tech`

## Quick Start

### Login
```bash
oc login -u admin --server=https://api.ocp-home.rh-lab.morey.tech:6443
```

## Deployed Applications

| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| Immich | immich | [immich.apps.ocp-home](https://immich.apps.ocp-home.rh-lab.morey.tech) | Photo/video management | Intel GPU, CloudNativePG |
| Immich (External) | immich | [immich.parents.morey.tech](https://immich.parents.morey.tech) | External access | Let's Encrypt cert, external-dns |
| Home Assistant | home-assistant | [hass.apps.ocp-home](https://hass.apps.ocp-home.rh-lab.morey.tech) | Home automation | MetalLB LoadBalancer |
| Home Assistant Code | home-assistant | [code-hass.apps.ocp-home](https://code-hass.apps.ocp-home.rh-lab.morey.tech) | Code-server for HA config | Sidecar container |
| Netbox | netbox | [netbox-netbox.apps.ocp-home](https://netbox-netbox.apps.ocp-home.rh-lab.morey.tech) | Infrastructure IPAM/DCIM | Helm chart |
| Paperless | paperless | [paperless.apps.ocp-home](https://paperless.apps.ocp-home.rh-lab.morey.tech) | Document management | Valkey (Redis), k8s-at-home |
| CCPT | ccpt | [ccpt.apps.ocp-home](https://ccpt.apps.ocp-home.rh-lab.morey.tech) | Custom application | - |
| Wingspan Scoring | wingspan-scoring | [wingspan-scoring.apps.ocp-home](https://wingspan-scoring.apps.ocp-home.rh-lab.morey.tech) | Custom application | - |
| RHSCA | rhsca | - | Custom application | - |
| backup-test | backup-test | - | Backup testing workload | Velero |

## Infrastructure Components

**Operators & System Services**:
- **OpenShift GitOps** - ArgoCD for GitOps deployment
- **OpenShift DevSpaces** - Cloud development environments
- **External Secrets Operator** - Bitwarden secret synchronization
- **Cert-Manager** - Let's Encrypt certificate automation
- **External-DNS** - Automatic DNS record creation
- **MetalLB** - Bare-metal load balancer
- **CloudNative-PG** - PostgreSQL operator
- **OpenShift Virtualization (CNV)** - VM workloads
- **OpenShift NFD** - Node Feature Discovery (GPU detection)
- **OpenShift Data Foundation** - Ceph storage (RBD, CephFS)
- **Velero** - Backup and disaster recovery

**Storage Classes**:
- `ocs-storagecluster-ceph-rbd` - Block storage (ODF)
- `ocs-storagecluster-cephfs` - Shared filesystem (ODF)
- `local-path` - Local node storage

## GitOps Structure

Applications are automatically discovered and deployed via ArgoCD ApplicationSets:

```
ocp-home/
├── bootstrap/                    # Initial ArgoCD setup
├── openshift-gitops-config/
│   ├── system-appset.yaml        # Auto-discovers system/*
│   └── applications-appset.yaml  # Auto-discovers applications/*
├── system/                       # Infrastructure components
│   ├── external-secrets/
│   ├── cert-manager/
│   ├── metalb/
│   └── ...
└── applications/                 # User-facing applications
    ├── immich/
    ├── home-assistant/
    ├── netbox/
    └── ...
```

## Cluster-Specific Features

### Intel GPU Support

This cluster includes hardware GPU acceleration using Intel i915 GPUs.

**GPU Detection**:
- OpenShift NFD labels nodes with GPU features
- Label: `feature.node.kubernetes.io/pci-0300_8086.present=true`

**GPU Resource Requests**:
```yaml
resources:
  limits:
    gpu.intel.com/i915: "1"
```

**Applications Using GPU**:
- **Immich**: Hardware video transcoding and ML acceleration

### External DNS & Custom Domains

The cluster uses `external-dns` to automatically create DNS records for selected applications.

**Configuration**:
- External-DNS creates A records in your DNS provider
- Applications opt-in via annotations
- Let's Encrypt certificates via cert-manager

**Example Route Annotations**:
```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/include: "true"
    external-dns.alpha.kubernetes.io/target: "192.168.0.20"
    cert-manager.io/cluster-issuer: letsencrypt-prod
```

**Public Domains**:
- `immich.parents.morey.tech` - External access to Immich with TLS

### Backup Strategy

- **Velero** backs up application namespaces
- **PV Snapshots** via ODF CSI driver
- **External Backups**: Immich photos backed up to external NAS (separate from Velero)

## Managing Applications

### Deploy New Application

1. Create directory in `applications/<app-name>/`
2. Add `kustomization.yaml` with resources
3. Commit to main branch
4. ArgoCD will auto-discover and sync within 3 minutes

```bash
# Example structure
mkdir -p applications/new-app
cat <<EOF > applications/new-app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: new-app

resources:
- namespace.yaml
- deployment.yaml
- service.yaml
- route.yaml
EOF

git add applications/new-app/
git commit -m "feat(ocp-home): add new-app application"
git push
```

### Update Existing Application

```bash
# Make changes in applications/<app-name>/
git add applications/<app-name>/
git commit -m "feat(ocp-home): update <app-name> configuration"
git push

# Check ArgoCD sync status
oc get app <app-name> -n openshift-gitops -o jsonpath='{.status.sync.status}'
```

### Test PR Changes

See [kubernetes/README.md - PR Testing Workflow](../README.md#pr-testing-workflow) for full workflow.

```bash
# Point ArgoCD app to PR branch for testing
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "feature-branch"}]'

# Check the diff
oc diff -f <(kustomize build --enable-helm applications/<app-name>/)

# After testing, restore to HEAD
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "HEAD"}]'
```

## Initial Setup

### Set Up HTPasswd Auth

Create HTPasswd file with `admin` user.
```bash
htpasswd -B -c ocp-home.htpasswd admin
# Enter password from Bitwarden: "OpenShift ocp-home admin password"
```

Create secret with HTPasswd contents.
```bash
oc create secret generic htpass-secret --from-file=htpasswd=ocp-home.htpasswd -n openshift-config
```

Add htpasswd identity provider and cluster role binding for admin user.
```bash
oc apply -f ./system/htpass-admin
```

## Troubleshooting

### Check Application Status

```bash
# ArgoCD application status
oc get app -n openshift-gitops | grep ocp-home

# Application pods
oc get pods -n <namespace>

# Application logs
oc logs -n <namespace> deployment/<app-name>
```

### Common Issues

**Image pull failures**:
- Check secret exists: `oc get secrets -n <namespace>`
- Verify External Secrets sync: `oc get externalsecret -n <namespace>`

**Route not accessible**:
- Verify route exists: `oc get route -n <namespace>`
- Check ingress controller: `oc get pods -n openshift-ingress`

**GPU not detected**:
- Check NFD labels: `oc get nodes -o json | jq '.items[].metadata.labels | with_entries(select(.key | startswith("feature.node.kubernetes.io/")))'`
- Verify GPU operator: `oc get pods -n openshift-nfd`

**External DNS not creating records**:
- Check external-dns logs: `oc logs -n external-dns deployment/external-dns`
- Verify route annotations are correct
- Check DNS provider credentials

## Related Documentation

- [Main Kubernetes README](../README.md) - GitOps workflow and common patterns
- [Immich Application README](applications/immich/README.md) - Immich-specific configuration
- [Home Assistant Application README](applications/home-assistant/README.md) - Home Assistant setup
- [Netbox Application README](applications/netbox/README.md) - Netbox configuration
