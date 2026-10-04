# Local NVMe LVM storage on ocp-mgmt

## Configuration

```bash
kustomize build kubernetes/ocp-mgmt/system/openshift-lvm-storage
oc get subscription,csv -n openshift-lvm-storage
oc get lvmcluster lvm-nvme -n openshift-lvm-storage -o yaml
oc get lvmvolumegroupnodestatus -n openshift-lvm-storage -o yaml
oc get storageclass lvms-vg-nvme -o yaml
```

The Red Hat LVM Storage Operator (`stable-4.22`) creates `lvms-vg-nvme` from device class `vg-nvme`. Argo CD manages the Subscription, namespace-scoped OperatorGroup and LVMCluster through `openshift-lvm-storage-system`.

| Setting | Value |
|---------|-------|
| Filesystem | XFS, supporting ID-mapped mounts for Dev Spaces user namespaces |
| Provisioner | `topolvm.io` |
| Access | Node-local ReadWriteOnce / ReadWriteOncePod; no replication or ReadWriteMany |
| Binding | `WaitForFirstConsumer`; provisioning follows pod placement and available node capacity |
| Expansion | Enabled by the operator-generated StorageClass |
| Reclaim policy | Operator default `Delete`; deleting a PVC deletes its local volume |
| Default class | No; workloads explicitly select `lvms-vg-nvme` |
| Thin pool | 90% of each selected disk, provisioning ratio 1 (no overprovisioning) |

A volume remains tied to its original node. A workspace cannot fail over to another node while keeping that volume. Back up important workspace data outside the node.

## Selected disks

Read-only inventory on 2026-10-04 found the following disks. Every selected Samsung disk is 2,000,398,934,016 bytes. The manifest uses complete `/dev/disk/by-id/` paths, not kernel device names, which can change across boots.

| Node | Selected serial | Observed device | Previous contents |
|------|-----------------|-----------------|-------------------|
| ms-02 | `S73WNU0XA10188H` | `nvme0n1` | ext4 partition |
| ms-04 | `S73WNU0XA10170M` | `nvme1n1` | Proxmox `local-nvme` VG and logical volumes |
| tr-gpu | `S73WNU0XA10179T` | `nvme1n1` | Former `lvm-nvme-vg`, shared with the excluded WD disk |

`ms-03` currently has only its 500 GB OS disk and is excluded. Add its hostname and verified 2 TB disk ID together when that drive is installed. The 500 GB OS disks on all nodes and tr-gpu's WD SN750 2 TB (`20530C800438`) are excluded. A future drive is not automatically enrolled.

`optionalPaths` contains one Samsung serial per selected node, allowing the other nodes' serials to be absent. At least one selected path must resolve on each included node. Never remove the explicit selector or add generic `/dev/nvme*` discovery: that could enroll the second tr-gpu drive.

## Destructive initialization and Argo CD rollout

**Forced wiping is enabled with the owner's authorization. Syncing the LVMCluster authorizes destruction of legacy data on the selected Samsung drives.** The old tr-gpu VG spans both its Samsung and WD disks, so destroying the Samsung member also makes the old shared pool unusable. The WD disk is not enrolled or directly selected for wiping by this configuration; it may retain stale metadata.

Force wiping does not guarantee that an active old VG, device-mapper holder, or busy partition can be reclaimed. The inventory showed active legacy LVM mappings on ms-04 and tr-gpu. If LVMS reports an unusable device, inspect its status and perform controlled legacy-pool cleanup separately before retrying. This configuration contains no host cleanup job, and no disk cleanup was executed while preparing it.

1. Review the selected serials and legacy-data destruction before syncing. Stop existing NFS-backed workspaces and preserve any uncommitted data before the Dev Spaces cutover.
2. Sync `openshift-lvm-storage-system` through Argo CD. OLM installs the operator; the LVMCluster uses wave 1, missing-CRD dry-run support and application retries while the CRD becomes available.
3. Confirm the LVMCluster and all three selected nodes report ready, and that `lvms-vg-nvme` exists with XFS and `WaitForFirstConsumer`.
4. Sync the Dev Spaces changes only after storage is ready. The ApplicationSet does not enforce readiness ordering between separate Applications; suspend its Dev Spaces automatic sync in the Argo CD UI during a staged rollout if needed.
5. Create a new workspace and run the checks in the [Dev Spaces README](../openshift-devspaces/README.md). A PVC can remain Pending until its first consumer is scheduled; this is expected with `WaitForFirstConsumer`.

The LVMCluster uses `Prune=confirm` to prevent ordinary automatic pruning from removing storage. Review removal explicitly. All deployment and runtime checks are performed by the operator of the cluster after Argo CD sync; preparation of these manifests made no cluster changes.

## References

- [Red Hat LVM Storage and device selection](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/storage/persistent-storage-using-local-storage)
- [LVM Storage 4.22 API](https://github.com/openshift/lvm-operator/blob/release-4.22/api/v1alpha1/lvmcluster_types.go)
- [Kubernetes user namespaces and filesystem requirements](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
