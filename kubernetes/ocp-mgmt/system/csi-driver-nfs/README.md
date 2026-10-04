# QNAP NFS Storage

`qnap-nvme` and `qnap-mass` dynamically provision NFS PersistentVolumes through the upstream NFS CSI driver. Each PVC gets its own directory on `qnap-01.rh-lab.morey.tech` (`192.168.6.20`). This replaces the need to hand-write a PV for each claim, as the existing `ocp-home` Immich/Paperless and former `ocp-gpu` AAP manifests do.

## StorageClass

| Setting | Value |
|---------|-------|
| Name | `qnap-nvme` or `qnap-mass` |
| Provisioner | `nfs.csi.k8s.io` |
| Export | `qnap-01.rh-lab.morey.tech:/storage-nvme` or `qnap-01.rh-lab.morey.tech:/storage-mass`, respectively |
| Directory | `ocp-mgmt/PVC_NAMESPACE/PVC_NAME-PV_NAME` beneath the export |
| Access | `ReadWriteMany` supported |
| Protocol | NFSv4.1, hard mounts |
| Reclamation | `Retain`; driver deletion policy also retains data |
| Default class | No; workloads explicitly select `qnap-nvme` or `qnap-mass` |

Requested PVC capacity and expansion are Kubernetes metadata, **not per-directory quotas**. Capacity limits must be enforced on QNAP separately. Retained data and released PVs require deliberate cleanup or recovery after a claim is deleted.

## QNAP Prerequisites

Export `/storage-nvme` and `/storage-mass` over NFS with read/write access for all management nodes: `192.168.6.91`, `.92`, `.93`, and `.94`. Root mapping/export permissions must allow the CSI controller to create and set permissions on claim directories. The driver sets permissions to `0777` only on newly provisioned claim directories so applications using OpenShift-assigned UIDs can write. Access to the export is controlled on QNAP; these directories are not separate filesystems.

From a cluster node, inspect the exports:

```bash
oc debug node/ms-02 -- chroot /host showmount -e qnap-01.rh-lab.morey.tech
```

## Use a PVC

For example, create a 10 GiB RWX claim in the existing `default` namespace:

```bash
oc apply -f - <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nfs-data
  namespace: default
spec:
  storageClassName: qnap-nvme
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi
YAML
oc get pvc nfs-data -n default
```

For the mass-storage export, set `storageClassName: qnap-mass`. Both classes use the same `ocp-mgmt/` directory layout beneath their respective exports.

Mount the claim from application pods using `persistentVolumeClaim.claimName: nfs-data`. Multiple pods in that namespace can mount it simultaneously on different nodes. Use application-appropriate storage for workloads requiring block devices or filesystem semantics beyond NFS.

## Driver Management

Argo CD manages `csi-driver-nfs-system` using Helm chart `4.13.4`. The controller runs on a control-plane/worker node; node plugins run on all four nodes, including `tr-gpu`. Only the driver service accounts receive the privileged SCC required for host mounts. Application pods use their normal OpenShift SCC. Snapshot controllers and snapshot CRDs are not installed by this component.

```bash
oc get application csi-driver-nfs-system -n openshift-gitops
oc get pods -n csi-driver-nfs-system -o wide
oc get csidriver nfs.csi.k8s.io
oc get storageclass qnap-nvme qnap-mass
oc get pvc,pv -A
```

For provisioning failures, inspect the claim's events and verify QNAP export permissions and NFS connectivity from the selected nodes.

- [NFS CSI chart documentation](https://github.com/kubernetes-csi/csi-driver-nfs/blob/master/charts/README.md)
- [Driver parameters](https://github.com/kubernetes-csi/csi-driver-nfs/blob/master/docs/driver-parameters.md)
