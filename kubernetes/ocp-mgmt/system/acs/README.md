# Advanced Cluster Security

ACS Central runs on `ocp-mgmt`, using the `rhacs-4.11` operator channel (catalog version 4.11.6 when prepared). Patch updates are automatic within that channel. Connecting `ocp-home` as a secured cluster is a follow-up change. The operator watches all namespaces from `rhacs-operator`; application resources live in `stackrox`.

| Endpoint | Purpose |
|----------|---------|
| [ACS portal](https://acs.apps.ocp-mgmt.rh-lab.morey.tech) | Browser/API access through a reencrypt route using the cluster ingress certificate |
| `acs-grpc.apps.ocp-mgmt.rh-lab.morey.tech:443` | Sensor connection through a passthrough route; preserves ACS TLS authentication |

Central DB requests 100 GiB and Scanner V4 DB requests 50 GiB on `lvms-vg-nvme`. This is node-local storage: databases cannot move to another node with their data after node loss. Back up Central separately. Scanner settings otherwise retain operator defaults. No SecuredCluster is installed on `ocp-mgmt`; workload observation requires connecting a secured cluster.

## GitOps deployment

```bash
oc kustomize kubernetes/ocp-mgmt/system/acs
```

1. Review and approve local commits, then push them to `main` yourself. Let Argo CD reconcile `acs-system` on `ocp-mgmt`. Do not apply local manifests directly.
2. On `ocp-mgmt`, wait for OLM, Central, Scanner and the database PVCs. Missing-CRD dry-run handling and retries allow OLM to install the APIs before the custom resources reconcile. Sync waves order resources inside each Application, not between clusters.
3. Log in to the portal as `admin`, using the generated password retrieved below. In **Platform Configuration → Clusters**, generate a cluster registration secret named `ocp-home` and securely download its YAML.
4. Store the registration credential securely for the subsequent `ocp-home` integration. Central alone does not collect workload network flows.

Run these commands while logged into `ocp-mgmt`:

```bash
oc get subscription,csv -n rhacs-operator
oc get central -n stackrox
oc get pods,pvc,route -n stackrox
# Run privately: prints the initial administrator password.
oc -n stackrox get secret central-htpasswd -o jsonpath='{.data.password}' | base64 --decode
```

`ocp-home` needs DNS resolution and outbound TCP 443 to the passthrough hostname. Test this from the deployed Sensor, checking its connection status and logs. The reencrypt browser route must not be used as the Sensor endpoint. Image pulls require working Red Hat registry credentials/entitlement through the OpenShift pull secret.

## Validation

Before deployment, render the Kustomization and validate Central against the matching operator CRDs. Server-side dry runs cannot validate Central until OLM installs their CRDs, and cannot validate namespaced resources against namespaces that do not yet exist.

After GitOps deployment, verify PVC binding, image pulls, both routes and portal login. Registration, Collector coverage and network-flow checks follow the secured-cluster integration. These runtime checks are deliberately deferred until deployment.

## References

- [RHACS installation and operator configuration](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.11/html-single/installing/index)
