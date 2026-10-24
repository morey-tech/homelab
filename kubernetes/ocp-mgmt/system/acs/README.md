# Advanced Cluster Security

ACS Central runs on `ocp-mgmt`; Sensor and Collector on `ocp-home` report workload connections to it. Both clusters use the `rhacs-4.11` operator channel (catalog version 4.11.6 when prepared). Patch updates are automatic within that channel. The operator watches all namespaces from `rhacs-operator`; application resources live in `stackrox`.

| Endpoint | Purpose |
|----------|---------|
| [ACS portal](https://acs.apps.ocp-mgmt.rh-lab.morey.tech) | Browser/API access through a reencrypt route using the cluster ingress certificate |
| `acs-grpc.apps.ocp-mgmt.rh-lab.morey.tech:443` | Sensor connection through a passthrough route; preserves ACS TLS authentication |

Central DB requests 100 GiB and Scanner V4 DB requests 50 GiB on `lvms-vg-nvme`. This is node-local storage: databases cannot move to another node with their data after node loss. Back up Central separately. Scanner settings otherwise retain operator defaults. No SecuredCluster is installed on `ocp-mgmt`; this setup observes `ocp-home` workloads.

## GitOps deployment

```bash
oc kustomize kubernetes/ocp-mgmt/system/acs
oc kustomize kubernetes/ocp-home/system/acs
```

1. Review and approve local commits, then push them to `main` yourself. Let Argo CD reconcile `acs-system` on each cluster. Do not apply local manifests directly.
2. On `ocp-mgmt`, wait for OLM, Central, Scanner and the database PVCs. Missing-CRD dry-run handling and retries allow OLM to install the APIs before the custom resources reconcile. Sync waves order resources inside each Application, not between clusters.
3. Log in to the portal as `admin`, using the generated password retrieved below. In **Platform Configuration → Clusters**, generate a cluster registration secret named `ocp-home` and securely download its YAML.
4. Complete the [ocp-home registration handoff](../../../ocp-home/system/acs/README.md). Apply the downloaded registration Secret manually after GitOps creates the `stackrox` namespace; the secured cluster waits for this credential on first installation. If initial sync retries expire, retry `acs-system` through Argo CD once the prerequisite is ready.
5. Verify Central reports `ocp-home` connected and Collector healthy. Confirm actual network flows before treating setup as complete.

Run these commands while logged into `ocp-mgmt`:

```bash
oc get subscription,csv -n rhacs-operator
oc get central -n stackrox
oc get pods,pvc,route -n stackrox
# Run privately: prints the initial administrator password.
oc -n stackrox get secret central-htpasswd -o jsonpath='{.data.password}' | base64 --decode
```

`ocp-home` needs DNS resolution and outbound TCP 443 to the passthrough hostname. Test this from the deployed Sensor, checking its connection status and logs. The reencrypt browser route must not be used as the Sensor endpoint. Image pulls require working Red Hat registry credentials/entitlement through the OpenShift pull secret.

## Inspect connections

Open **Network Graph**, select `ocp-home`, choose the namespaces and observation window, and display **Active** flows. Select a workload and inspect its flows for peers, direction, protocol and ports. Exercise ordinary application workflows, scheduled tasks and integrations to build a representative connection history. The **Allowed** view reflects policy permissions rather than proof of traffic.

Collector uses `CORE_BPF` on all nodes, including tainted nodes. ACS primarily attributes traffic to workloads; it is not a packet capture or HTTP URL log, and cannot recover traffic from before collection started. IPs covered by configured CIDR blocks can appear aggregated. Admission enforcement is disabled on `ocp-home`; review any future enforcement or generated NetworkPolicies as a separate GitOps change.

## Validation

Before deployment, render both Kustomizations and validate Central/SecuredCluster against the matching operator CRDs. Server-side dry runs cannot validate those custom resources until OLM installs their CRDs, and cannot validate namespaced resources against namespaces that do not yet exist.

After GitOps deployment, verify PVC binding, image pulls, both routes, registration Secret availability, cluster registration, Collector coverage and actual internal/external flows. These runtime checks are deliberately deferred until deployment.

## References

- [RHACS installation and operator configuration](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.11/html-single/installing/index)
- [Network Graph](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.11/html/operating/manage-network-policies)
- [Collector runtime configuration](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.11/html/operating/using-collector-runtime-configuration)
