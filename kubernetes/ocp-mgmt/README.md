# OpenShift Cluster: ocp-mgmt

Management and testing cluster for Ansible Automation Platform, DevSpaces, and demo workloads.

## Cluster Information

- **API Endpoint**: `https://api.ocp-mgmt.rh-lab.morey.tech:6443`
- **Console**: `https://console-openshift-console.apps.ocp-mgmt.rh-lab.morey.tech`
- **ArgoCD**: `https://openshift-gitops-server-openshift-gitops.apps.ocp-mgmt.rh-lab.morey.tech`

## Quick Start

### Login
```bash
oc login -u admin --server=https://api.ocp-mgmt.rh-lab.morey.tech:6443
```

## Deployed Applications

### Production Applications

| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| Ansible Automation Platform | ansible-automation-platform | [aap.ocp-mgmt.morey.tech](https://aap.ocp-mgmt.morey.tech) | Automation controller | Custom domain, AAP operator |
| AnythingLLM | anythingllm | [anythingllm.apps.ocp-mgmt](https://anythingllm-anythingllm.apps.ocp-mgmt.rh-lab.morey.tech) | LLM chat/RAG application | 10m timeout |
| Netbox | netbox | [netbox-netbox.apps.ocp-mgmt](https://netbox-netbox.apps.ocp-mgmt.rh-lab.morey.tech) | Infrastructure IPAM/DCIM | Helm chart |
| vLLM CPU | vllm-cpu | [vllm-cpu.apps.ocp-mgmt](https://vllm-cpu-vllm-cpu.apps.ocp-mgmt.rh-lab.morey.tech) | CPU-based LLM inference | No GPU required |
| CCPT | ccpt | [ccpt.apps.ocp-mgmt](https://ccpt.apps.ocp-mgmt.rh-lab.morey.tech) | Custom application | - |
| Wingspan Scoring | wingspan-scoring | [wingspan-scoring.apps.ocp-mgmt](https://wingspan-scoring.apps.ocp-mgmt.rh-lab.morey.tech) | Custom application | - |
| RHSCA | rhsca | - | Custom application | - |

### Testing/Demo Workloads

| Application | Namespace | URL | Purpose | Notes |
|-------------|-----------|-----|---------|-------|
| netbox-broken | netbox-broken | [netbox-demo.apps.ocp-mgmt](https://netbox-demo.apps.ocp-mgmt.rh-lab.morey.tech) | Intentionally broken Netbox | Demo/troubleshooting |
| uid-gid-in-action | uid-gid-in-action | - | Security context demo | SCC testing |
| demo | demo | - | General demo workloads | Testing |

## Infrastructure Components

**Operators & System Services**:
- **OpenShift GitOps** - ArgoCD for GitOps deployment
- **OpenShift DevSpaces** - Cloud development environments (runs here!)
- **Ansible Automation Platform Operator** - AAP lifecycle management
- **External Secrets Operator** - Bitwarden secret synchronization
- **Cert-Manager** - Let's Encrypt certificate automation
- **OpenShift Virtualization (CNV)** - VM workloads
- **OpenShift Data Foundation** - Ceph storage

## Cluster-Specific Features

### Ansible Automation Platform

AAP provides centralized automation and webhooks for infrastructure management.

**Access**: [https://aap.ocp-mgmt.morey.tech](https://aap.ocp-mgmt.morey.tech)

**Capabilities**:
- Centralized playbook execution
- Webhook-triggered automation
- Job templates and workflows
- Credential management

**Common Tasks**:
```bash
# Check AAP operator status
oc get pods -n ansible-automation-platform-operator

# View AAP resources
oc get automationcontroller -n ansible-automation-platform
```

### OpenShift DevSpaces

This cluster hosts the OpenShift DevSpaces instance used for development.

**Features**:
- Automatic extension installation (Claude Code, Ansible)
- Pre-configured development tools
- Workspace creation from repository URL
- Integration with OpenShift clusters

**Check DevSpaces Status**:
```bash
# DevSpaces operator
oc get pods -n openshift-devspaces

# CheCluster configuration
oc get checluster -n openshift-devspaces
```

### Demo/Testing Workloads

This cluster includes intentionally broken or test applications for demos and troubleshooting practice.

**netbox-broken**: Demonstrates troubleshooting scenarios
**uid-gid-in-action**: Security context and SCC testing
**demo**: General testing workloads

## Managing Applications

### Deploy Application

```bash
mkdir -p applications/my-app
cat <<EOF > applications/my-app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: my-app

resources:
- namespace.yaml
- deployment.yaml
EOF

git add applications/my-app/
git commit -m "feat(ocp-mgmt): add my-app for testing"
git push
```

### AAP Webhook Integration

Configure AAP job templates with webhooks for event-driven automation.

```bash
# Example: Trigger AAP job from OpenShift
oc create secret generic aap-webhook \
  --from-literal=url=https://aap.ocp-mgmt.morey.tech/api/v2/job_templates/XX/github/

# Add webhook annotation to trigger jobs
metadata:
  annotations:
    webhook.aap/job-template: "my-template"
```

## Initial Setup

### Set Up HTPasswd Auth

Create HTPasswd file with `admin` user.
```bash
htpasswd -B -c ocp-mgmt.htpasswd admin
# Enter password from Bitwarden: "OpenShift ocp-mgmt admin password"
```

Create secret with HTPasswd contents.
```bash
oc create secret generic htpass-secret --from-file=htpasswd=ocp-mgmt.htpasswd -n openshift-config
```

Add htpasswd identity provider and cluster role binding for admin user.
```bash
oc apply -f ./system/htpass-admin
```

## Troubleshooting

### Check AAP Status

```bash
# AAP operator
oc get pods -n ansible-automation-platform-operator

# AAP instance
oc get automationcontroller -n ansible-automation-platform

# AAP logs
oc logs -n ansible-automation-platform deployment/<aap-deployment>
```

### Check DevSpaces Status

```bash
# DevSpaces operator
oc get pods -n openshift-devspaces

# Che server
oc get checluster -n openshift-devspaces -o yaml

# User workspaces
oc get devworkspace -A
```

### Common Issues

**AAP webhook not firing**:
- Check webhook URL is correct
- Verify network connectivity
- Review AAP job template configuration
- Check OpenShift events for errors

**DevSpaces workspace failing to start**:
- Check DevWorkspace status: `oc get devworkspace -A`
- Review che-server logs: `oc logs -n openshift-devspaces deployment/devspaces`
- Verify PVC creation for workspace storage

## Related Documentation

- [Main Kubernetes README](../README.md) - GitOps workflow and common patterns
- [Ansible Automation Platform Documentation](https://access.redhat.com/documentation/en-us/red_hat_ansible_automation_platform)
- [OpenShift DevSpaces Documentation](https://access.redhat.com/documentation/en-us/red_hat_openshift_dev_spaces)
