# Morey Tech Homelab

Production-grade homelab infrastructure running multiple OpenShift clusters with GitOps deployment, demonstrating enterprise Kubernetes patterns, AI/ML workloads, and home automation.

## Architecture Overview

This homelab consists of:
- **5 OpenShift Clusters** - Production, GPU-accelerated AI/ML, management, lab, and local development environments
- **GitOps Deployment** - ArgoCD ApplicationSets for automated multi-cluster management
- **Infrastructure as Code** - Ansible playbooks for configuration management and Terraform for provisioning
- **Automated Dependency Management** - Renovate for continuous updates of Helm charts, container images, and Ansible collections
- **Custom Container Images** - Multi-architecture (amd64/arm64) development containers

### Infrastructure Layers

```
┌─────────────────────────────────────────────────────────┐
│  Applications & Services                                 │
│  (Immich, Home Assistant, AAP, AnythingLLM, etc.)       │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  GitOps Layer (ArgoCD ApplicationSets)                  │
│  Automated deployment from Git                          │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Kubernetes/OpenShift Clusters                          │
│  ocp-home | ocp-gpu | ocp-mgmt | ocp-lab | kind         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Virtualization & Infrastructure                        │
│  Proxmox VE (Ansible managed)                           │
└─────────────────────────────────────────────────────────┘
```

## Cluster Environments

| Cluster | Purpose | API Endpoint | Key Features |
|---------|---------|--------------|--------------|
| [ocp-home](kubernetes/ocp-home/README.md) | Production workloads | api.ocp-home.rh-lab.morey.tech:6443 | Intel GPU, 8 applications, external DNS |
| [ocp-gpu](kubernetes/ocp-gpu/README.md) | GPU-accelerated AI/ML | api.ocp-gpu.rh-lab.morey.tech:6443 | NVIDIA GPUs, vLLM, AnythingLLM |
| [ocp-mgmt](kubernetes/ocp-mgmt/README.md) | Management & testing | api.ocp-mgmt.rh-lab.morey.tech:6443 | AAP, DevSpaces, demo workloads |
| [ocp-lab](kubernetes/ocp-lab/README.md) | Lab experiments | api.ocp-lab.rh-lab.morey.tech:6443 | Testing environment |
| [kind-personal](kubernetes/kind-personal/README.md) | Local development | localhost | Kind cluster bootstrap |

## Repository Structure

```
homelab/
├── kubernetes/          # GitOps Kubernetes manifests
│   ├── ocp-home/       # Production cluster - Immich, Home Assistant, Netbox, Paperless
│   ├── ocp-gpu/        # GPU cluster - AnythingLLM, inference servers
│   ├── ocp-mgmt/       # Management cluster - AAP, DevSpaces, demos
│   ├── ocp-lab/        # Lab cluster - Testing and experiments
│   ├── kind-personal/  # Local Kind cluster
│   ├── rubrik/         # Rubrik environment
│   └── README.md       # GitOps workflow documentation
│
├── ansible/            # Infrastructure automation
│   ├── playbooks/      # Proxmox, pfSense, UniFi automation
│   └── README.md       # Renovate workflow for Ansible collections
│
├── terraform/          # Infrastructure provisioning
│   ├── rubrik/         # MAAS-based bare-metal provisioning
│   └── README.md       # Terraform usage documentation
│
├── containers/         # Custom container images
│   ├── devcontainer/   # Development environment (multi-arch)
│   ├── hf-cli/         # HuggingFace CLI tool
│   └── README.md       # Container build conventions
│
├── docs/               # Documentation and decision records
│   └── decision-records/ # MADR architectural decisions
│
├── .devcontainer/      # VS Code DevContainer configuration
├── devfile.yaml        # OpenShift DevSpaces configuration
└── AGENTS.md           # Claude Code workflow documentation
```

## Development Environment

This repository includes a complete development environment with all required tools pre-installed.

### OpenShift DevSpaces (Recommended)

Cloud-based development environment running on the ocp-mgmt cluster.

**Access**: Navigate to your OpenShift DevSpaces instance and create workspace from:
```
https://github.com/morey-tech/homelab
```

**Included Tools**: oc, kubectl, kustomize, helm, ansible, terraform, gh CLI

**Extensions**: Automatically installs Claude Code and Ansible extensions via [.vscode/extensions.json](.vscode/extensions.json)

**Auto-configured Credentials** (ocp-gpu cluster):
- **GitHub CLI**: Authenticated using DevSpaces OAuth credentials (no setup required)
- **Claude Code**: API key injected from Bitwarden as `ANTHROPIC_API_KEY` environment variable

The Claude Code extension will automatically authenticate using the API key when you open a workspace.

### Local DevContainer

For local development with VS Code:

```bash
# Clone repository
git clone https://github.com/morey-tech/homelab.git
cd homelab

# Open in VS Code
code .

# Reopen in Container when prompted
```

**Requirements**: Docker or Podman, VS Code with Dev Containers extension

**Container Image**: `ghcr.io/morey-tech/homelab/devcontainer:latest` (multi-arch: amd64/arm64)

**Manual Configuration Required**:
- **GitHub CLI**: Run `gh auth login` after container starts
- **Claude Code**: Set `ANTHROPIC_API_KEY` environment variable or use Claude.ai subscription

See [containers/devcontainer/README.md](containers/devcontainer/README.md) for details.

## Quick Start

### Exploring Clusters

```bash
# Login to production cluster
oc login -u admin --server=https://api.ocp-home.rh-lab.morey.tech:6443

# View all ArgoCD applications
oc get applications -n openshift-gitops

# Check deployed pods across all namespaces
oc get pods -A

# View application routes
oc get routes -A
```

### Testing Configuration Changes

```bash
# Validate Kustomize build locally
kustomize build --enable-helm kubernetes/ocp-home/system/external-secrets/

# Test on live cluster (see kubernetes/README.md for full PR workflow)
oc -n openshift-gitops patch application <app-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "feature-branch"}]'
```

### Running Ansible Playbooks

```bash
cd ansible
ansible-playbook upgrade.yml
```

See subsystem READMEs for detailed workflows.

## Components

### Kubernetes GitOps

GitOps-based deployment using ArgoCD ApplicationSets for multi-cluster management.

**Key Features**:
- Automated application discovery via directory structure
- Kustomize + Helm integration for manifest management
- External Secrets Operator with Bitwarden backend
- PR testing workflow for safe updates
- ServerSideApply for large CRDs

**Documentation**: [kubernetes/README.md](kubernetes/README.md)

**Common Patterns**:
- [GitOps workflow](kubernetes/README.md#gitops-workflow)
- [PR testing](kubernetes/README.md#pr-testing-workflow)
- [Kustomize with Helm](kubernetes/README.md#kustomize-with-helm-charts)
- [OpenShift compatibility](kubernetes/README.md#openshift-compatibility)

### Ansible Configuration Management

Automated management of Proxmox hosts, pfSense firewall, and UniFi network controller.

**Capabilities**:
- Proxmox VE host upgrades and configuration
- VM provisioning and lifecycle management
- Network device configuration (pfSense, UniFi)
- Renovate-based automated Ansible Galaxy collection updates

**Documentation**: [ansible/README.md](ansible/README.md)

**Workflows**:
- [Renovate PR testing](ansible/README.md#renovate-pr-workflow)
- [Breaking change handling](ansible/README.md#handling-breaking-changes)

### Terraform Infrastructure

Bare-metal infrastructure provisioning via MAAS (Metal as a Service) for the Rubrik environment.

**Documentation**: [terraform/README.md](terraform/README.md)

### Container Images

Custom multi-architecture container images for development and tooling.

**Standards**:
- OCI-compliant Containerfiles (not Dockerfile)
- Multi-architecture support (arm64 and amd64)
- Automated builds via GitHub Actions

**Documentation**: [containers/README.md](containers/README.md)

## Workflows

### Issue-to-PR Workflow

This repository uses Claude Code for implementing features and fixes following a structured workflow.

**Process**: Create issue → Comment with approach → Create branch → Implement → Test → Create PR → Merge

**Documentation**: [AGENTS.md](AGENTS.md)

### Dependency Management

Automated dependency updates via Renovate with custom testing workflows.

**Kubernetes Dependencies**:
- Helm chart version updates
- Container image tag updates
- CRD version migrations
- Testing: [kubernetes/README.md - PR Testing Workflow](kubernetes/README.md#pr-testing-workflow)

**Ansible Dependencies**:
- Ansible Galaxy collection updates
- Breaking change detection
- Testing: [ansible/README.md - Renovate PR Workflow](ansible/README.md#renovate-pr-workflow)

### Decision Records

Architectural decisions are documented using MADR (Markdown Any Decision Records).

**Location**: [docs/decision-records/](docs/decision-records/)

**Template**: [docs/decision-records/xxxx-template.md](docs/decision-records/xxxx-template.md)

## Contributing

### Development Setup

1. Set up development environment (DevSpaces or local DevContainer - see above)
2. Authenticate to clusters (see cluster-specific READMEs)
3. Familiarize yourself with the GitOps workflow: [kubernetes/README.md](kubernetes/README.md)

### Making Changes

```bash
# Create feature branch
git checkout -b feat/<feature-name>
# or for fixes:
git checkout -b fix/<fix-name>

# Make changes following existing patterns
# Test locally with kustomize/ansible/terraform

# Create PR with descriptive title and body
gh pr create --title "feat: description" --body "..."
```

### Testing

**Kubernetes Changes**:
1. Local validation: `kustomize build --enable-helm <path>`
2. Live cluster testing by pointing ArgoCD app to PR branch
3. Verify pods are running: `oc get pods -n <namespace>`
4. Check for breaking changes (see [kubernetes/README.md](kubernetes/README.md#checking-for-breaking-changes))

**Ansible Changes**:
1. Syntax check: `ansible-playbook --syntax-check <playbook>.yml`
2. Test playbook execution: `ansible-playbook <playbook>.yml`
3. Verify breaking changes in collection updates

**Terraform Changes**:
1. Format check: `terraform fmt -check`
2. Validate: `terraform validate`
3. Plan: `terraform plan`

### PR Review and Merge

See [AGENTS.md](AGENTS.md) for the standard Claude Code workflow.

For manual PRs:
1. Ensure all tests pass
2. Get review approval
3. Merge with squash: `gh pr merge <pr-number> --squash --delete-branch`

## Technology Stack

**Kubernetes Platform**:
- Red Hat OpenShift 4.x (RHEL CoreOS)
- ArgoCD / OpenShift GitOps
- Kustomize + Helm

**Infrastructure**:
- Proxmox VE (virtualization)
- Ansible (configuration management)
- Terraform + MAAS (bare-metal provisioning)
- pfSense (network routing/firewall)
- UniFi (network management)

**Storage**:
- OpenShift Data Foundation (Ceph)
- CloudNative-PG (PostgreSQL operator)
- Local PV provisioner
- External NFS/SMB

**Security**:
- External Secrets Operator (Bitwarden backend)
- Cert-Manager (Let's Encrypt)
- HTPasswd authentication
- OpenShift Security Context Constraints (SCC)

**AI/ML**:
- NVIDIA GPU Operator
- vLLM inference server
- AnythingLLM RAG application
- Intel GPU support (i915)

**Automation**:
- Renovate (dependency updates)
- GitHub Actions (container builds)
- ArgoCD (continuous deployment)
