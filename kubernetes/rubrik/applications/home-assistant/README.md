# Home Assistant Migration: rubrik → ocp-home

Migration jobs for moving Home Assistant from rubrik (MicroK8s) to ocp-home (OpenShift).

## Prerequisites

- NFS share accessible from both clusters at `/storage-mass/rubrik`
- Home Assistant deployed on ocp-home with PVC created
- `kubectl` access to rubrik cluster
- `oc` access to ocp-home cluster

## Migration Steps

### 1. Scale down Home Assistant on rubrik
```bash
kubectl --kubeconfig=/tmp/rubrik-kubeconfig.yaml scale deployment home-assistant --replicas=0 -n home-assistant
```

### 2. Run backup job on rubrik
```bash
kubectl --kubeconfig=/tmp/rubrik-kubeconfig.yaml apply -f backup-job.yaml
kubectl --kubeconfig=/tmp/rubrik-kubeconfig.yaml wait --for=condition=complete job/home-assistant-backup -n home-assistant --timeout=300s
kubectl --kubeconfig=/tmp/rubrik-kubeconfig.yaml logs job/home-assistant-backup -n home-assistant
```

### 3. Scale down Home Assistant on ocp-home
```bash
oc scale deployment home-assistant --replicas=0 -n home-assistant
```

### 4. Run restore job on ocp-home
```bash
oc apply -f restore-job.yaml
oc wait --for=condition=complete job/home-assistant-restore -n home-assistant --timeout=120s
oc logs job/home-assistant-restore -n home-assistant
```

### 5. Scale up Home Assistant on ocp-home
```bash
oc scale deployment home-assistant --replicas=1 -n home-assistant
```

### 6. Configure trusted proxies

Add the OpenShift router IP to `configuration.yaml`:
```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 192.168.6.0/24  # OpenShift pod network
```

### 7. Cleanup

Delete temporary restore resources:
```bash
oc delete job home-assistant-restore -n home-assistant
oc delete pvc home-assistant-backup -n home-assistant
oc delete pv home-assistant-backup-nfs
```

Delete backup job on rubrik:
```bash
kubectl --kubeconfig=/tmp/rubrik-kubeconfig.yaml delete job home-assistant-backup -n home-assistant
```

## Notes

- The restore job creates a temporary PV/PVC for NFS access (required on OpenShift)
- Backup file is stored at `/storage-mass/rubrik/home-assistant-<timestamp>.tar.gz`
- The `storageClassName: ""` is required to bind to a specific PV on OpenShift
