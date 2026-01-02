# OpenShift Cluster: ocp-gpu

NVIDIA GPU-accelerated cluster for AI/ML workloads and inference servers.

## Cluster Information

- **API Endpoint**: `https://api.ocp-gpu.rh-lab.morey.tech:6443`
- **Console**: `https://console-openshift-console.apps.ocp-gpu.rh-lab.morey.tech`
- **ArgoCD**: `https://openshift-gitops-server-openshift-gitops.apps.ocp-gpu.rh-lab.morey.tech`

## Quick Start

### Login
```bash
oc login -u admin --server=https://api.ocp-gpu.rh-lab.morey.tech:6443
```

## Deployed Applications

| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| AnythingLLM | anythingllm | [anythingllm.apps.ocp-gpu](https://anythingllm-anythingllm.apps.ocp-gpu.rh-lab.morey.tech) | LLM chat/RAG application | 10m timeout, GPU acceleration |
| Inference Server | inference-server | [inference.apps.ocp-gpu](https://inference-server-inference-server.apps.ocp-gpu.rh-lab.morey.tech) | vLLM inference endpoint | NVIDIA GPU, 10m timeout |

## Infrastructure Components

**Operators & System Services**:
- **OpenShift GitOps** - ArgoCD for GitOps deployment
- **OpenShift DevSpaces** - Cloud development environments
- **NVIDIA GPU Operator** - NVIDIA GPU support and device plugin
- **External Secrets Operator** - Bitwarden secret synchronization
- **Cert-Manager** - Let's Encrypt certificate automation
- **OpenShift NFD** - Node Feature Discovery
- **OpenShift Pipelines** - Tekton CI/CD pipelines
- **OpenShift Data Foundation** - Ceph storage

**Storage Classes**:
- `ocs-storagecluster-ceph-rbd` - Block storage (ODF)
- `ocs-storagecluster-cephfs` - Shared filesystem (ODF)

## Cluster-Specific Features

### NVIDIA GPU Support

This cluster includes NVIDIA GPUs for accelerated AI/ML workloads.

**GPU Operator**:
- Automatically installs NVIDIA drivers
- Provides GPU device plugin
- Supports MIG (Multi-Instance GPU) partitioning
- GPU monitoring and metrics

**GPU Resource Requests**:
```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

**Check GPU Availability**:
```bash
# List nodes with GPUs
oc get nodes -l feature.node.kubernetes.io/pci-10de.present=true

# Check GPU operator pods
oc get pods -n nvidia-gpu-operator

# View GPU capacity
oc describe node <node-name> | grep -A 10 "Allocatable"
```

### Inference Server Configuration

Inference servers require longer timeouts due to LLM processing time.

**Route Timeout Configuration**:
```yaml
metadata:
  annotations:
    haproxy.router.openshift.io/timeout: "10m"
```

**Typical Inference Workloads**:
- vLLM for high-throughput inference
- Text generation models (Llama, Mistral, etc.)
- Embedding models for RAG applications

## Managing Applications

### Deploy ML Workload

```bash
# Example: Deploy LLM inference server
mkdir -p applications/my-llm
cat <<EOF > applications/my-llm/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: my-llm

resources:
- namespace.yaml
- deployment.yaml
- service.yaml
- route.yaml
EOF

# deployment.yaml should include GPU resource request
# resources:
#   limits:
#     nvidia.com/gpu: "1"

git add applications/my-llm/
git commit -m "feat(ocp-gpu): add my-llm inference server"
git push
```

### Monitor GPU Usage

```bash
# Check GPU utilization on nodes
oc debug node/<node-name>
chroot /host
nvidia-smi

# Check GPU allocation
oc get pods -A -o json | jq '.items[] | select(.spec.containers[].resources.limits."nvidia.com/gpu" != null) | {name: .metadata.name, namespace: .metadata.namespace, gpu: .spec.containers[].resources.limits."nvidia.com/gpu"}'
```

### Update Application

```bash
# Make changes to application
git add applications/<app-name>/
git commit -m "feat(ocp-gpu): update <app-name> inference model"
git push

# Check ArgoCD sync status
oc get app <app-name> -n openshift-gitops -o jsonpath='{.status.sync.status}'
```

## Initial Setup

### Set Up HTPasswd Auth

Create HTPasswd file with `admin` user.
```bash
htpasswd -B -c ocp-gpu.htpasswd admin
# Enter password from Bitwarden: "OpenShift ocp-gpu admin password"
```

Create secret with HTPasswd contents.
```bash
oc create secret generic htpass-secret --from-file=htpasswd=ocp-gpu.htpasswd -n openshift-config
```

Add htpasswd identity provider and cluster role binding for admin user.
```bash
oc apply -f ./system/htpass-admin
```

## Troubleshooting

### Check GPU Status

```bash
# GPU operator status
oc get pods -n nvidia-gpu-operator
oc logs -n nvidia-gpu-operator deployment/nvidia-gpu-operator

# Node GPU labels
oc get nodes -o json | jq '.items[].metadata.labels' | grep nvidia

# GPU device plugin
oc get daemonset -n nvidia-gpu-operator
```

### Common Issues

**GPU not detected**:
- Verify GPU operator is running: `oc get pods -n nvidia-gpu-operator`
- Check node labels: `oc get nodes --show-labels | grep nvidia`
- Review driver installation: `oc logs -n nvidia-gpu-operator -l app=nvidia-driver-daemonset`

**Inference server timeout**:
- Verify route timeout annotation is set to `10m` or higher
- Check application logs for processing time
- Consider increasing timeout for large models

**Out of GPU memory**:
- Check GPU allocation: `nvidia-smi` on node
- Reduce model size or batch size
- Consider enabling MIG for GPU partitioning
- Check for memory leaks in application

**Pod pending with FailedScheduling**:
- Check GPU availability: `oc describe node <node-name>`
- Verify GPU resource request is correct
- Ensure node has GPUs labeled correctly

## Related Documentation

- [Main Kubernetes README](../README.md) - GitOps workflow and common patterns
- [NVIDIA GPU Operator Documentation](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)
- [AnythingLLM Application README](applications/anythingllm/README.md) - AnythingLLM configuration
