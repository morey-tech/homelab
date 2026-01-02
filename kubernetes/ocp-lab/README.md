# OpenShift Cluster: ocp-lab

Experimental and testing cluster for lab workloads.

## Cluster Information

- **API Endpoint**: `https://api.ocp-lab.rh-lab.morey.tech:6443`
- **Console**: `https://console-openshift-console.apps.ocp-lab.rh-lab.morey.tech`
- **ArgoCD**: `https://openshift-gitops-server-openshift-gitops.apps.ocp-lab.rh-lab.morey.tech`

## Quick Start

### Login
```bash
oc login -u admin --server=https://api.ocp-lab.rh-lab.morey.tech:6443
```

## Deployed Applications

| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| Netbox | netbox | [netbox-netbox.apps.ocp-lab](https://netbox-netbox.apps.ocp-lab.rh-lab.morey.tech) | Infrastructure IPAM/DCIM | Testing instance |

## Infrastructure Components

**Operators & System Services**:
- **OpenShift GitOps** - ArgoCD for GitOps deployment (minimal bootstrap)

## Purpose

This cluster serves as an experimental environment for:
- Testing new configurations before production
- Evaluating new operators and applications
- Learning and experimentation
- Breaking things safely

## Initial Setup

### Set Up HTPasswd Auth

Create HTPasswd file with `admin` user.
```bash
htpasswd -B -c ocp-lab.htpasswd admin
# Enter password from Bitwarden: "OpenShift ocp-lab admin password"
```

Create secret with HTPasswd contents.
```bash
oc create secret generic htpass-secret --from-file=htpasswd=ocp-lab.htpasswd -n openshift-config
```

Add htpasswd identity provider and cluster role binding for admin user.
```bash
oc apply -f ./system/htpass-admin
```

## Related Documentation

- [Main Kubernetes README](../README.md) - GitOps workflow and common patterns
