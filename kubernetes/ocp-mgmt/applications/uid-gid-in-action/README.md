# NFS Permissions and OpenShift Security Context Constraints Demo

## Overview

This demonstration shows how OpenShift pods can access NFS shares that contain batch job results, exploring different Security Context Constraint (SCC) configurations and their impact on file access permissions.

**User Story**: A batch job system writes result files to an NFS share. OpenShift pods need to read these results to display them to users. The challenge is configuring the pods with appropriate UID/GID settings to access the NFS share while maintaining security best practices.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      NFS Server                             │
│               nfs.lab.morey.tech (192.168.3.54)             │
│                                                             │
│  /srv/nfs/share/results/                                    │
│    ├── batch-job-1.txt  (2001:2001, mode 0640)              │
│    ├── batch-job-2.txt  (2001:2001, mode 0640)              │
│    └── ...                                                  │
│                                                             │
│  NFS Export: root_squash enabled                            │
└─────────────────────────────────────────────────────────────┘
         ▲                                   ▲
         │ Writes                            │ Reads
         │ (as UID 2001)                     │ (various UIDs)
         │                                   │
┌────────┴───────────┐              ┌────────┴────────────┐
│   Batch Job        │              │   OpenShift Cluster │
│   batch-job.lab    │              │     ocp-mgmt        │
│                    │              │                     │
│  Runs as:          │              │  4 Scenarios:       │
│  labuser (2001)    │              │  1. Default UID     │
│                    │              │  2. Suppl. Groups   │
│                    │              │  3. anyuid SCC      │
│                    │              │  4. Custom SCC      │
└────────────────────┘              └─────────────────────┘
```

## Infrastructure Components

### NFS Server Users

| Username | UID | Primary GID | Supplemental Groups | Purpose |
|----------|-----|-------------|---------------------|---------|
| labuser | 2001 | 2001 | - | Batch job executor, file owner |
| serviceaccount | 3001 | 3001 | 2001 (labuser) | Demo user for supplemental group access |
| poduser | 4001 | 0 | - | Demo of UID/GID similar to a Pod in OpenShift |

### Batch Job Server

- **Host**: `batch-job.lab.morey.tech` (192.168.3.55)
- **Runs as**: labuser (UID 2001, GID 2001)
- **Function**: Writes batch job results to `/mnt/nfs/share/results/`

### OpenShift Cluster

- **Cluster**: `ocp-mgmt`
- **Namespace**: `uid-gid-in-action`
- **Function**: Read batch job results from NFS share via various pod configurations

## NFS Share File Permissions

### Directory Structure

```
/srv/nfs/share/
└── results/                    (owned by 2001:2001, mode 0750)
    ├── batch-job-1.txt         (owned by 2001:2001, mode 0640)
    ├── batch-job-2.txt         (owned by 2001:2001, mode 0640)
    ├── batch-job-3.txt         (owned by 2001:2001, mode 0640)
    ├── batch-job-4.txt         (owned by 2001:2001, mode 0640)
    └── batch-job-5.txt         (owned by 2001:2001, mode 0640)
```

### Permission Breakdown

**Directory: `/srv/nfs/share/results`**
- **Ownership**: labuser:labuser (2001:2001)
- **Mode**: `0750` (rwxr-x---)
  - Owner (labuser): read, write, execute
  - Group (labuser/2001): read, execute
  - Other: no permissions

**Files: `batch-job-*.txt`**
- **Ownership**: labuser:labuser (2001:2001)
- **Mode**: `0640` (rw-r-----)
  - Owner (labuser): read, write
  - Group (labuser/2001): read only
  - Other: no permissions

**Access Requirements**:
- Users with UID 2001 have full read/write access (owner)
- Users with supplemental group 2001 can read directory and files but **cannot write**
- All other users have no access

## OpenShift Scenarios

### Scenario 1: Default Arbitrary UID ❌

**File**: [auto-uid-deploy.yaml](auto-uid-deploy.yaml)

**Configuration**:
```yaml
spec:
  # No serviceAccountName specified (uses default)
  # No securityContext specified
  # Nothing special configured - completely default deployment
```

**What Happens**:
- Uses the default service account
- OpenShift's restricted SCC assigns an arbitrary UID from the namespace's UID range annotation (e.g., 1000660000)
- Pod runs with primary GID 0 (root)
- No supplemental groups are set

**Result**: ❌ **Access DENIED**

**Why it Fails**:
1. The arbitrary UID (e.g., 1000660000) comes from OpenShift's project-specific UID range
2. This arbitrary UID is very unlikely to exist as a user on the NFS server
3. The arbitrary UID doesn't match the file owner (2001) or group (2001)
4. Note: `root_squash` only maps UID 0 (root), not arbitrary UIDs
5. The arbitrary UID simply tries to access files as itself and gets permission denied
6. Files are owned by 2001:2001 with permissions 0640 (rw-r-----), so the arbitrary UID has no read/write access

**Key Lesson**: Arbitrary UIDs from OpenShift's restricted SCC don't work with NFS because the UID range is specific to OpenShift and doesn't align with NFS server users. Without matching UIDs or proper group membership, access is denied.

---

### Scenario 2: Supplemental Groups Only ❌

**File**: [supplemental-groups-deploy.yaml](supplemental-groups-deploy.yaml) (same file, demonstrates same failure mode)

**Configuration**:
```yaml
spec:
  # No serviceAccountName specified
  securityContext:
    supplementalGroups:
      - 2001
```

**What Happens**:
- Pod gets arbitrary UID from namespace range
- Supplemental group 2001 is configured
- Pod attempts to access NFS share using supplemental group permissions

**Result**: ❌ **Access DENIED**

**Why it Fails**:
1. The UID is unmapped on the NFS server (doesn't exist in `/etc/passwd` or LDAP)
2. **NFS uses "managed GIDs"** by default - it looks up the user locally/via LDAP to determine supplemental groups
3. Since the UID doesn't exist on the NFS server, the server cannot determine what supplemental groups the user should have
4. The supplemental groups passed by the client are **ignored** by the NFS server
5. Access falls to "other" permissions (none)

**Key Lesson**: Supplemental groups alone don't work with NFS if the UID doesn't exist on the server. The NFS server must be able to look up the user to trust supplemental group membership.

---

### Scenario 3: anyuid SCC with Explicit UID/GID ✅

**Files**:
- [serviceaccount-deploy-sa.yaml](serviceaccount-deploy-sa.yaml)
- [serviceaccount-deploy-anyuid-binding.yaml](serviceaccount-deploy-anyuid-binding.yaml)
- [serviceaccount-deploy.yaml](serviceaccount-deploy.yaml)

**Configuration**:
```yaml
spec:
  serviceAccountName: serviceaccount-deploy-sa
  securityContext:
    runAsUser: 3001
    runAsGroup: 3001
    supplementalGroups:
      - 2001
```

**What Happens**:
- Pod uses ServiceAccount bound to `anyuid` SCC
- Explicitly sets UID 3001 and primary GID 3001
- Adds supplemental group 2001
- UID 3001 exists on the NFS server (serviceaccount user)

**Result**: ✅ **Access GRANTED (Read-Only)**

**Why it Works**:
1. `anyuid` SCC allows setting any UID/GID values
2. UID 3001 (serviceaccount) exists on the NFS server
3. The NFS server can look up UID 3001 and find supplemental group 2001
4. Supplemental group 2001 grants read access to files (mode 0640, group=r--)
5. Write access is denied (correct - files are 0640, group has read-only)

**Drawback**: `anyuid` SCC is very permissive - it allows ANY UID to be specified, which may be a security concern.

**Key Lesson**: Explicitly setting UID/GID to match a server-side user enables supplemental group permissions to work correctly with NFS.

---

### Scenario 4: Custom SCC with Allowed UID Range ✅ (Best Practice)

**Files**:
- [scc-allowed-uid-3001.yaml](scc-allowed-uid-3001.yaml) - Custom SCC definition
- [allowed-uid-3001-clusterrole.yaml](allowed-uid-3001-clusterrole.yaml) - ClusterRole for SCC access
- [allowed-uid-3001-sa.yaml](allowed-uid-3001-sa.yaml) - ServiceAccount
- [allowed-uid-3001-binding.yaml](allowed-uid-3001-binding.yaml) - RoleBinding
- [allowed-uid-3001-deploy.yaml](allowed-uid-3001-deploy.yaml) - Working deployment (UID 3001)
- [blocked-uid-2001-deploy.yaml](blocked-uid-2001-deploy.yaml) - Blocked deployment (UID 2001)

**SCC Configuration**:
```yaml
runAsUser:
  type: MustRunAsRange
  uidRangeMin: 3001
  uidRangeMax: 3001
supplementalGroups:
  type: RunAsAny
priority: 10
```

**Deployment Configuration**:
```yaml
spec:
  serviceAccountName: allowed-uid-3001-sa
  securityContext:
    runAsUser: 3001
    runAsGroup: 3001
    supplementalGroups:
      - 2001
```

**What Happens**:
- Custom SCC restricts `runAsUser` to exactly UID 3001
- ServiceAccount is bound to this SCC via RoleBinding → ClusterRole
- Deployment sets UID 3001, primary GID 3001, supplemental group 2001
- SCC admission controller validates and allows UID 3001
- Attempting UID 2001 is **blocked** by admission controller

**Result**: ✅ **Access GRANTED (Read-Only)** for UID 3001, ❌ **Blocked** for UID 2001

**Why it's Best Practice**:
1. **Least Privilege**: Unlike `anyuid` which allows ANY UID, this SCC only allows UID 3001
2. **Explicit Control**: You define exactly which UIDs are permitted
3. **Namespace-Scoped**: RoleBinding limits access to specific namespace
4. **Admission Control**: Invalid UIDs are rejected before pod creation
5. **Security**: Prevents privilege escalation to other UIDs

**Comparison to anyuid**:

| Feature | anyuid SCC | Custom SCC (allowed-uid-3001) |
|---------|------------|-------------------------------|
| Allowed UIDs | Any UID | Only 3001 |
| Security Risk | High - any UID can be used | Low - specific UID only |
| Use Case | Development, flexibility | Production, specific workload |
| Cluster-wide? | Yes (via ClusterRoleBinding) | No (via RoleBinding) |

**Key Lesson**: Custom SCCs provide fine-grained control over which UIDs can be used, reducing security risk while still enabling necessary NFS access.

## Key Concepts

### root_squash

**What it is**: NFS server setting that maps root (UID 0) and unknown UIDs to `nobody`/`nfsnobody` for security.

**Impact**:
- Prevents arbitrary UIDs from accessing NFS shares
- Requires UIDs to exist on the NFS server
- Default behavior on most NFS servers

### Managed GIDs

**What it is**: NFS server behavior where it looks up the user (by UID) on the server to determine supplemental groups, rather than trusting the client.

**Impact**:
- Client-specified supplemental groups are ignored for unmapped UIDs
- UID must exist in `/etc/passwd` or LDAP for supplemental groups to work
- Prevents clients from falsely claiming group membership

### UID Mapping

**What it is**: Process of matching a numeric UID to a user account on the NFS server.

**Mapped UID** (exists on server):
- NFS can determine permissions correctly
- Supplemental groups work
- Example: UID 3001 → serviceaccount user

**Unmapped UID** (doesn't exist on server):
- NFS maps to `nobody`
- Supplemental groups ignored
- Example: UID 1000660000 → nobody

### Custom SCC vs anyuid SCC

**anyuid SCC**:
- ✅ Allows any UID to be specified
- ❌ Very permissive, security risk
- ✅ Quick solution for development
- ✅ Pre-existing, no custom resources needed

**Custom SCC** (like allowed-uid-3001):
- ✅ Restricts to specific UIDs only
- ✅ Least privilege approach
- ✅ Better for production
- ❌ Requires creating ClusterRole + RoleBinding
- ✅ Namespace-scoped via RoleBinding

## Deployment Order

### Infrastructure Setup

1. Deploy NFS server and batch job system:
   ```bash
   ansible-playbook -i ansible/inventory/hosts.yml ansible/lab-nfs-create.yml
   ```

2. Verify NFS is working:
   ```bash
   ssh root@nfs.lab.morey.tech "ls -la /srv/nfs/share/results/"
   ```

### OpenShift Setup

1. Create namespace and PV/PVC:
   ```bash
   oc apply -f namespace.yaml
   oc apply -f pv-nfs.yaml
   oc apply -f pvc-nfs.yaml
   ```

2. **Scenario 1 & 2**: Default/Supplemental Groups (will fail):
   ```bash
   oc apply -f supplemental-groups-deploy.yaml
   ```

3. **Scenario 3**: anyuid SCC (will succeed):
   ```bash
   oc apply -f serviceaccount-deploy-sa.yaml
   oc apply -f serviceaccount-deploy-anyuid-binding.yaml
   oc apply -f serviceaccount-deploy.yaml
   ```

4. **Scenario 4**: Custom SCC (will succeed for 3001, block 2001):
   ```bash
   # Requires cluster-admin
   oc apply -f scc-allowed-uid-3001.yaml
   oc apply -f allowed-uid-3001-clusterrole.yaml

   # Can be applied by namespace admin
   oc apply -f allowed-uid-3001-sa.yaml
   oc apply -f allowed-uid-3001-binding.yaml
   oc apply -f allowed-uid-3001-deploy.yaml

   # This will be blocked by admission controller
   oc apply -f blocked-uid-2001-deploy.yaml
   ```

## Verification

### Check Pod UID/GID

```bash
POD=$(oc get pod -n uid-gid-in-action -l app=allowed-uid-3001-test -o jsonpath='{.items[0].metadata.name}')
oc exec -n uid-gid-in-action $POD -- id
```

Expected output:
```
uid=3001(serviceaccount) gid=3001(serviceaccount) groups=2001(labuser),3001(serviceaccount)
```

### Check NFS Access

```bash
# List files
oc exec -n uid-gid-in-action $POD -- ls -la /mnt/nfs/share/results/

# Read file (should work)
oc exec -n uid-gid-in-action $POD -- cat /mnt/nfs/share/results/batch-job-1.txt

# Try to write (should fail - read-only access)
oc exec -n uid-gid-in-action $POD -- touch /mnt/nfs/share/results/test.txt
```

### Check Which SCC is Used

```bash
oc get pod -n uid-gid-in-action $POD -o yaml | grep 'openshift.io/scc'
```

Expected: `openshift.io/scc: allowed-uid-3001`

## Summary

This demonstration shows that accessing NFS shares from OpenShift requires careful UID/GID configuration:

1. **Default arbitrary UIDs fail** due to `root_squash` and unmapped UIDs
2. **Supplemental groups alone don't work** because NFS uses managed GIDs and ignores client-provided groups for unmapped UIDs
3. **Explicit UID mapping is required** - the UID must exist on the NFS server
4. **anyuid SCC works but is overly permissive** - allows any UID to be specified
5. **Custom SCCs provide the best balance** of functionality and security by restricting to specific allowed UIDs

**Best Practice**: Create custom SCCs that explicitly list allowed UIDs, create matching users on the NFS server, and use RoleBindings to limit scope to specific namespaces.

## Cleanup

```bash
ansible-playbook -i ansible/inventory/hosts.yml ansible/lab-nfs-destroy.yml
```
