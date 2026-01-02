# Terraform Infrastructure Provisioning

Bare-metal infrastructure provisioning using Terraform with MAAS (Metal as a Service).

## Overview

This directory contains Terraform configurations for provisioning bare-metal infrastructure for the homelab environment.

## Directory Structure

```
terraform/
└── rubrik/         # Rubrik lab environment provisioning
    ├── maas.tf           # MAAS provider and VM resources
    ├── providers.tf      # Provider configuration
    ├── variables.tf      # Variable definitions
    └── README.md         # Rubrik-specific documentation
```

## Prerequisites

- Terraform >= 1.0
- MAAS API access
- MAAS API key

## Usage

### Initialize Terraform

```bash
cd terraform/rubrik
terraform init
```

### Plan Changes

```bash
terraform plan
```

### Apply Configuration

```bash
terraform apply
```

### Destroy Resources

```bash
terraform destroy
```

## Environments

### Rubrik Lab

MAAS-based bare-metal provisioning for the Rubrik testing environment.

**Documentation**: [rubrik/README.md](rubrik/README.md)

**Purpose**:
- Provision bare-metal VMs via MAAS
- Rubrik testing and demonstration
- Separate from OpenShift clusters

## Best Practices

- Always run `terraform plan` before `terraform apply`
- Use version control for state management
- Document infrastructure changes
- Test in lab environment before production

## Related Documentation

- [Rubrik Environment README](rubrik/README.md)
- [Kubernetes README](../kubernetes/README.md) - For cluster configuration
- [Ansible README](../ansible/README.md) - For configuration management
