# Example app

Render the manifests from the repository root:

```bash
kustomize build kubernetes/ocp-mgmt/applications/example-app
```

A small Python HTTP server serves a page from persistent storage. No image build or dependency installation is needed. The Python standard-library server is intended for this demo.

| Resource | Purpose |
|----------|---------|
| Deployment | One non-root pod serving HTTP on port 8080, with health probes and a Recreate update strategy |
| Service | Sends traffic to the pod's named HTTP port |
| PersistentVolumeClaim / PersistentVolume | A 1 GiB `lvms-vg-nvme` claim dynamically provisions a node-local PV mounted at `/data` |
| Route | Edge TLS with HTTP-to-HTTPS redirect, using the cluster's wildcard certificate |
| ConfigMap | Supplies the initial `index.html`, copied to the volume only when the file is absent |

The PV is created by LVM Storage after pod scheduling (`WaitForFirstConsumer`), so no static PV manifest or pre-created storage directory is needed. OpenShift assigns the pod's user and volume group through its restricted SCC. The volume is node-local and not replicated. The PVC is protected from automatic Argo CD pruning/deletion; explicitly deleting the claim deletes its backing volume under this storage class's `Delete` reclaim policy.

The initial page is preserved across pod replacements. Changing the ConfigMap seed does not overwrite an existing `/data/index.html`.

## Deployment and verification

The ocp-mgmt ApplicationSet includes this directory and creates the `example-app` namespace. Review and approve the local commit, then push it manually and let Argo CD reconcile. Do not apply the local manifests directly.

After GitOps deployment:

```bash
oc get application example-app -n openshift-gitops
oc rollout status deployment/example-app -n example-app --timeout=120s
oc get deployment,pods,service,pvc,route -n example-app
oc get pv "$(oc get pvc example-app -n example-app -o jsonpath='{.spec.volumeName}')"
curl --fail https://example-app.apps.ocp-mgmt.rh-lab.morey.tech/index.html
```

Open [the example app](https://example-app.apps.ocp-mgmt.rh-lab.morey.tech). After a later GitOps deployment replaces the pod, verify the mounted page remains available. Volume provisioning, SCC admission, image pull, HTTPS routing, and persistence across pod replacements require post-deployment checks.
