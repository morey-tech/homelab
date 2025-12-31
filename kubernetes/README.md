# Kubernetes GitOps Configuration

This directory contains Kubernetes manifests managed via GitOps using ArgoCD.

## Directory Structure

```
kubernetes/
├── ocp-home/          # Production OpenShift cluster
├── ocp-gpu/           # GPU-enabled OpenShift cluster
├── ocp-mgmt/          # Management OpenShift cluster
├── ocp-lab/           # Lab OpenShift cluster
├── kind-personal/     # Local Kind cluster
├── rubrik/            # Rubrik environment
└── helm/              # Shared Helm configurations
```

Each cluster directory follows this structure:
```
<cluster>/
├── bootstrap/              # Initial cluster setup
├── openshift-gitops-config/ # ArgoCD ApplicationSets
├── system/                 # Infrastructure components
└── applications/           # User-facing applications
```

## GitOps Workflow

### ArgoCD ApplicationSets

Applications are managed via ApplicationSets that auto-discover directories:

- **system-appset.yaml**: Discovers `system/*` directories
- **applications-appset.yaml**: Discovers `applications/*` directories

### PR Testing Workflow

When testing Renovate or manual PRs that update dependencies:

#### 1. Checkout and Local Validation
```bash
# Checkout the PR branch
gh pr checkout <PR_NUMBER>

# Test kustomize build locally
kustomize build --enable-helm kubernetes/<cluster>/system/<component>/
```

#### 2. Live Cluster Testing
```bash
# Disable auto-sync to prevent automatic changes
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/syncPolicy/automated/enabled", "value": false}]'

# Point app to PR branch
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "<branch-name>"}]'

# Check the diff
oc diff -f <(kustomize build --enable-helm kubernetes/<cluster>/system/<component>/)

# Enable auto-sync to apply changes
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/syncPolicy/automated/enabled", "value": true}]'
```

#### 3. Verify and Merge
```bash
# Verify pods are running
oc get pods -n <namespace>

# Merge the PR
gh pr merge <PR_NUMBER> --squash --delete-branch

# Restore app to HEAD
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "HEAD"}]'
```

## Common Patterns and Techniques

### Kustomize with Helm Charts

Helm charts are integrated via Kustomize's `helmCharts` field:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: example-system

helmCharts:
- name: example-chart
  includeCRDs: true
  version: 1.0.0
  repo: https://charts.example.io
  releaseName: example
  namespace: example-system
  valuesInline:
    key: value
```

Build with: `kustomize build --enable-helm <path>`

### OpenShift Compatibility

Many Helm charts include `runAsUser` in security contexts, which conflicts with OpenShift's SCC. Solutions:

**Option 1: Built-in Chart Support** (preferred)
```yaml
valuesInline:
  global:
    compatibility:
      openshift:
        adaptSecurityContext: force
```

**Option 2: JSON Patch** (fragile - fails if field doesn't exist)
```yaml
patches:
- target:
    kind: Deployment
    name: example
  patch: |
    - op: remove
      path: /spec/template/spec/containers/0/securityContext/runAsUser
```

### Large CRD Handling

CRDs exceeding 262,144 bytes fail with client-side apply due to annotation limits. Use ServerSideApply:

**Via ApplicationSet templatePatch:**
```yaml
templatePatch: |
  {{- if eq .path.basename "external-secrets" }}
  spec:
    syncPolicy:
      syncOptions:
      - allowEmpty=true
      - CreateNamespace=true
      - ServerSideApply=true
  {{ end }}
```

### API Version Migrations

When upgrading operators, check for API version changes:

```bash
# Check current API versions in use
oc get <resource> -A -o jsonpath='{.items[*].apiVersion}' | tr ' ' '\n' | sort -u

# Check available versions in CRD
oc get crd <crd-name> -o jsonpath='{.spec.versions[*].name}'
```

Update manifests from deprecated versions (e.g., `v1beta1` to `v1`).

## Checking for Breaking Changes

When reviewing dependency updates, check for:

| Issue | Detection | Solution |
|-------|-----------|----------|
| JSON patch failures | Patch removes non-existent field | Use chart's built-in options or strategic merge patch |
| API version changes | `oc get crd` shows only newer versions | Update manifest apiVersion |
| Large CRDs | CRD YAML > 262KB | Enable ServerSideApply |
| SCC conflicts | Pods fail with security context errors | Use OpenShift compatibility settings |
| Missing resources | ArgoCD shows "missing" status | Check if CRDs need `SkipDryRunOnMissingResource` |

## Useful Commands

```bash
# Check ArgoCD app status
oc get app <app-name> -n openshift-gitops -o jsonpath='{.status.sync.status}'

# Check app health
oc get app <app-name> -n openshift-gitops -o jsonpath='{.status.health.status}'

# Force refresh
oc -n openshift-gitops annotate application <app-name> argocd.argoproj.io/refresh=hard --overwrite

# View sync errors
oc get app <app-name> -n openshift-gitops -o jsonpath='{.status.operationState.message}'

# Check CRD size
oc get crd <crd-name> -o yaml | wc -c
```

## External Secrets

Secrets are managed via External Secrets Operator with Bitwarden as the backend:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: example-secret
spec:
  target:
    name: example-secret
    deletionPolicy: Delete
  data:
  - secretKey: password
    sourceRef:
      storeRef:
        name: bitwarden-login
        kind: ClusterSecretStore
    remoteRef:
      key: <bitwarden-item-id>
      property: password
```

Available ClusterSecretStores:
- `bitwarden-login` - Access login credentials (username/password)
- `bitwarden-fields` - Access custom fields
- `bitwarden-notes` - Access secure notes
