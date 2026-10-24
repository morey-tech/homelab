# ACS secured cluster: ocp-home

Sensor and the eBPF Collector report to [Central on ocp-mgmt](../../../ocp-mgmt/system/acs/README.md). Admission enforcement is disabled. `collector-config` enables external egress IP collection as well as normal workload connection collection.

## Registration handoff

After the approved manifests are pushed, let Argo CD deploy `acs-system` on `ocp-home`. Wait for the `stackrox` namespace and operator to exist. SecuredCluster will wait for its registration credential; this is expected during initial bootstrap.

Generate a cluster registration secret (CRS) in Central and download it as `ocp-home-cluster-registration-secret.yaml`. This local filename is Git-ignored. The credential is supplied manually, with no ExternalSecret managing it. After GitOps creates the namespace, apply the downloaded Secret:

```bash
oc --context ocp-home-tailnet get namespace stackrox
oc --context ocp-home-tailnet apply -n stackrox -f ./ocp-home-cluster-registration-secret.yaml
```

This creates `stackrox/cluster-registration-secret`; no decoding is necessary. Retry `acs-system` through Argo CD if its initial sync retries expired while waiting for prerequisites.

A CRS is reusable until expiry or revocation, including for registering a rebuilt cluster against the existing Central. After registration, Central issues service certificates for ongoing communication. You can revoke the CRS without disconnecting registered clusters, but it can no longer bootstrap a rebuilt cluster. Keep it securely if you intend to reuse it. Follow Central's documented recovery procedure if service certificates are lost; replacing the CRS alone is not a certificate repair.

## Verify after GitOps deployment

Run while logged into `ocp-home`:

```bash
oc get subscription,csv -n rhacs-operator
oc -n stackrox get secret cluster-registration-secret
oc -n stackrox get securedcluster stackrox-secured-cluster-services
oc -n stackrox get pods,daemonsets
oc -n stackrox logs deployment/sensor --tail=100
```

Confirm the Collector DaemonSet is ready on every node and Central reports `ocp-home` connected. Open **Network Graph → ocp-home**, select **Active** traffic and exercise an application with known internal and off-cluster dependencies. Check the resulting destination IPs, ports and direction. See the [Central runbook](../../../ocp-mgmt/system/acs/README.md) for endpoint, storage and network visibility details.
