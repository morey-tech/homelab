# NFS Permissions Testing Scenario

## Overview

This scenario demonstrates NFS share access patterns and permissions by comparing behavior between a simulated batch job system (LXC container) and OpenShift pods. The setup includes:

- **NFS Server**: `nfs.lab.morey.tech` (192.168.3.54) serving `/srv/nfs/share`
- **Batch Job System**: `batch-job.lab.morey.tech` (192.168.3.55) - LXC container simulating a traditional batch processing environment
- **OpenShift Cluster**: `ocp-mgmt` cluster with pods consuming the same NFS share

The scenario simulates a real-world use case where:
1. A batch job runs and generates results to an NFS share
2. An OpenShift pod needs to consume those results from the same NFS share
3. The pod requires read-only access via supplemental groups

## User Types and Configurations

### 1. labuser (UID: 2001, GID: 2001)

**Purpose**: Primary user running the batch job and owning result files.

**Configuration**:
- UID: 2001
- Primary GID: 2001
- Supplemental groups: None
- Exists on: Both NFS server and batch job system

**NFS Share Access**:
- Full read/write access to `/srv/nfs/share/results` (owner permissions)
- Owns all batch job result files (mode 0640)
- Directory `/srv/nfs/share/results` owned by labuser:labuser (mode 0750)

**OpenShift Equivalent**: N/A - this represents the batch job executor

### 2. serviceaccount (UID: 3001, GID: 3001)

**Purpose**: Demonstrates a user with supplemental group access that CAN access the NFS share when properly configured in OpenShift.

**Configuration**:
- UID: 3001
- Primary GID: 3001
- Supplemental groups: `labuser` (GID 2001)
- Exists on: Both NFS server and batch job system

**NFS Share Access**:
- **Can access** `/srv/nfs/share/results` directory via supplemental group membership
- Primary GID 3001 doesn't match directory GID 2001, but supplemental GID 2001 does
- Requires explicit UID/GID configuration in OpenShift pod spec
- **Demonstrates**: Supplemental groups work when the UID exists on the NFS server and is explicitly set

**OpenShift Equivalent**: Pod with `runAsUser: 3001`, `runAsGroup: 3001`, and `supplementalGroups: [2001]`

**Important**: This only works in OpenShift because:
1. The `serviceaccount` user exists on the NFS server
2. Both `runAsUser` and `runAsGroup` are explicitly set (requires anyuid SCC)
3. The supplemental group 2001 is configured on the NFS server for this user

### 3. poduser (UID: 4001, Primary GID: 0, Supplemental: 2001)

**Purpose**: Simulates OpenShift pod behavior where the primary GID is 0 (root) but supplemental groups are added.

**Configuration**:
- UID: 4001
- Primary GID: 0 (root)
- Supplemental groups: `labuser` (GID 2001)
- Exists on: Batch job system only (not on NFS server)

**NFS Share Access**:
- **Cannot access** `/srv/nfs/share/results` directory (mode 0750)
- Primary GID 0 doesn't match directory GID 2001
- Supplemental GID 2001 is ignored for permission checks
- UID 4001 doesn't exist on NFS server (maps to `nobody` with root_squash)
- **Demonstrates**: Exactly matches OpenShift pod behavior with supplementalGroups when UID/GID are not explicitly set

**OpenShift Equivalent**: Default OpenShift pod with `supplementalGroups: [2001]` but no explicit runAsUser/runAsGroup

### 4. Arbitrary OpenShift UID (No specific configuration)

**Purpose**: Demonstrates default OpenShift pod behavior without any security context constraints.

**Configuration**:
- UID: Random (assigned by OpenShift, typically in range 1000660000-1000669999)
- Primary GID: 0 (root)
- Supplemental groups: None (unless explicitly configured)

**NFS Share Access**:
- **Cannot access** `/srv/nfs/share/results` directory
- UID doesn't exist on NFS server
- Primary GID 0 doesn't match directory GID 2001
- **Demonstrates**: Default OpenShift pods cannot access restrictive NFS shares

**OpenShift Configuration**: `supplemental-groups-deploy.yaml`

## Comparison of Access Patterns

| User Type | UID | Primary GID | Supplemental GID | Can Access NFS? | Reason |
|-----------|-----|-------------|------------------|----------------|--------|
| labuser | 2001 | 2001 | - | Yes | Owner of directory and files |
| serviceaccount | 3001 | 3001 | 2001 | **Yes** (with explicit UID/GID) | User exists on NFS server, supplemental group 2001 grants access |
| poduser | 4001 | 0 | 2001 | **No** | Primary GID ≠ 2001, UID unmapped on NFS server |
| Arbitrary UID | ~1000660000 | 0 | - | **No** | UID unmapped, Primary GID ≠ 2001 |

## Key Findings

### When Supplemental Groups Work vs. Don't Work

**Supplemental groups work when**:
- The UID running the process exists on the NFS server
- The UID/GID are explicitly set to match the server-side user
- The user on the NFS server has the supplemental group configured
- Example: `serviceaccount` (UID 3001) with supplemental GID 2001

**Supplemental groups DON'T work when**:
- The UID doesn't exist on the NFS server (unmapped UID)
- The process runs as an arbitrary UID assigned by OpenShift
- Example: `poduser` (UID 4001) which doesn't exist on the NFS server

### Linux Permission Check Order

Linux permission checks follow this order:
1. **UID check**: If the UID matches the file/directory owner
2. **Primary GID check**: If the primary GID matches the file/directory group
3. **Supplemental groups check**: If any supplemental GID matches the file/directory group
4. **"Other" permissions**: If none of the above match

**Critical insight**: Supplemental groups ARE checked, but only after the primary GID check. For supplemental groups to work with NFS:
- The UID must exist on the NFS server (not be unmapped)
- The user must have the supplemental group configured on the NFS server
- Both UID and GID must be explicitly set in the pod security context

### fsGroup Limitations

Setting `fsGroup: 2001` in OpenShift:
- Changes the group ownership of **volumes** to GID 2001
- Does NOT change the primary GID of the running process
- Only affects the volume mount point, not the NFS server's permission checks
- **Does not solve** the NFS access issue for files owned on the NFS server side

## Solution: ServiceAccount with anyuid SCC

The best practice for achieving the same experience as the batch job user is to use a ServiceAccount with access to the `anyuid` Security Context Constraint.

### Components

1. **ServiceAccount** ([serviceaccount-deploy-sa.yaml](serviceaccount-deploy-sa.yaml))
   ```yaml
   apiVersion: v1
   kind: ServiceAccount
   metadata:
     name: serviceaccount-deploy-sa
   ```

2. **ClusterRoleBinding** ([serviceaccount-deploy-anyuid-binding.yaml](serviceaccount-deploy-anyuid-binding.yaml))
   ```yaml
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRoleBinding
   metadata:
     name: serviceaccount-deploy-anyuid-binding
   roleRef:
     apiGroup: rbac.authorization.k8s.io
     kind: ClusterRole
     name: system:openshift:scc:anyuid
   subjects:
     - kind: ServiceAccount
       name: serviceaccount-deploy-sa
       namespace: uid-gid-in-action
   ```

3. **Deployment** ([serviceaccount-deploy.yaml](serviceaccount-deploy.yaml))
   ```yaml
   spec:
     serviceAccountName: serviceaccount-deploy-sa
     securityContext:
       runAsUser: 3001
       runAsGroup: 3001
       supplementalGroups:
         - 2001
   ```

### Why This Works

The `anyuid` SCC allows explicitly setting `runAsUser` and `runAsGroup`:
- Setting `runAsUser: 3001` runs the pod process as UID 3001 (serviceaccount user)
- Setting `runAsGroup: 3001` sets the primary GID to 3001 (serviceaccount group)
- The `serviceaccount` user exists on the NFS server with supplemental group 2001
- NFS permission checks see the mapped UID 3001 with supplemental GID 2001
- Access is granted via the supplemental group membership to labuser (GID 2001)

**Key requirement**: The UID must exist on the NFS server for supplemental groups to work. This is why:
- `serviceaccount` (UID 3001) works - user exists on NFS server
- `poduser` (UID 4001) doesn't work - user doesn't exist on NFS server
- Arbitrary OpenShift UIDs don't work - unmapped on NFS server

### Alternative: Match the Batch Job User Exactly

For direct file ownership access (not relying on supplemental groups):
```yaml
spec:
  serviceAccountName: serviceaccount-deploy-sa
  securityContext:
    runAsUser: 2001
    runAsGroup: 2001
```

This provides owner-level access since the pod runs as the exact same UID/GID as the batch job.

## Testing the Scenario

### Deploy the Infrastructure

1. Create the LXC containers and NFS server:
   ```bash
   ansible-playbook -i ansible/inventory/hosts.yml ansible/lab-nfs-create.yml
   ```

2. Verify NFS mount on batch job system:
   ```bash
   ssh root@batch-job.lab.morey.tech "mountpoint /mnt/nfs/share"
   ```

3. Check test files exist:
   ```bash
   ssh root@nfs.lab.morey.tech "ls -la /srv/nfs/share/results/"
   ```

### Deploy OpenShift Resources

1. Apply the namespace and PV/PVC:
   ```bash
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/namespace.yaml
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/pv-nfs.yaml
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/pvc-nfs.yaml
   ```

2. Test with supplemental groups only (will fail - arbitrary UID):
   ```bash
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/supplemental-groups-deploy.yaml
   ```

3. Test with serviceaccount and anyuid SCC (will succeed - mapped UID with supplemental groups):
   ```bash
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/serviceaccount-deploy-sa.yaml
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/serviceaccount-deploy-anyuid-binding.yaml
   oc apply -f kubernetes/ocp-mgmt/applications/uid-gid-in-action/serviceaccount-deploy.yaml
   ```

### Verify Access

Test from within the pods:
```bash
# Get pod name
POD=$(oc get pod -n uid-gid-in-action -l app=serviceaccount-test -o name | head -1)

# Check user/group
oc exec -n uid-gid-in-action $POD -- id

# List NFS files
oc exec -n uid-gid-in-action $POD -- ls -la /mnt/nfs/share/results/

# Read a test file
oc exec -n uid-gid-in-action $POD -- cat /mnt/nfs/share/results/batch-job-1.txt
```

## Cleanup

Destroy the test environment:
```bash
ansible-playbook -i ansible/inventory/hosts.yml ansible/lab-nfs-destroy.yml
```

## Summary

This scenario demonstrates that:

1. **Supplemental groups work with NFS when the UID exists on the NFS server** - you must explicitly set both runAsUser and runAsGroup to match a server-side user
2. **Arbitrary UIDs cannot use supplemental groups** - unmapped UIDs prevent supplemental group permissions from working
3. **fsGroup does not change the process GID**, only the volume mount point ownership
4. **The anyuid SCC is required** to explicitly set UID/GID in OpenShift
5. **Best practice**: Create matching users on the NFS server, use anyuid SCC to set explicit UID/GID, and leverage supplemental groups for access control

The proper configuration allows OpenShift pods to achieve the same NFS access experience as traditional batch job systems while maintaining security through RBAC and SCC controls.
