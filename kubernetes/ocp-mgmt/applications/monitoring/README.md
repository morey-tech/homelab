# Monitoring Foundation

Grafana, infrastructure Prometheus, Grafana Alloy, and Blackbox Exporter are hosted in the `monitoring` namespace on `ocp-mgmt`. The application ApplicationSet explicitly enables this directory.

This phase installs the services without collecting metrics. Grafana has no provisioned data sources or dashboards; Prometheus has no scrape jobs (including itself), discovery, recording rules, remote read/write, or enabled ingestion receivers. Alloy contains only logging configuration. Blackbox Exporter defines HTTP and TCP modules but has no callers or targets. No OpenShift monitoring credentials, ServiceMonitors, PodMonitors, device credentials, or device integrations are installed. The existing OpenShift monitoring stacks are unchanged.

## Services and Storage

| Service | Image version | Storage | Access |
|---------|---------------|---------|--------|
| Grafana | 13.2.3 | 5 GiB | [grafana.apps.ocp-mgmt.rh-lab.morey.tech](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech) |
| Prometheus | 3.15.0 | 100 GiB | `prometheus.monitoring.svc:9090` |
| Alloy | 1.20.1 | 5 GiB | `alloy.monitoring.svc:12345` |
| Blackbox Exporter | 0.29.0 | None | `blackbox-exporter.monitoring.svc:9115` |

All persistent volumes use `lvms-vg-nvme`. Required node affinity limits every workload to `ms-02` or `ms-04`; `ms-03` has no configured NVMe volume group, and `tr-gpu` is reserved for other workloads. OpenShift assigns the UID and volume group through the explicitly required `restricted-v2` SCC; no fixed UID, privileged init container, host mount, or extra SCC is required.

Each Deployment has one replica. Recreate updates release each ReadWriteOnce volume before starting its replacement. Volumes are node-local and are not replicated: loss of a storage node takes its service offline until the node recovers or data is restored. PVC annotations require confirmation before Argo CD pruning and preserve claims when the Application is deleted. The storage class has a Delete reclaim policy, so manually deleting a PVC can still destroy its data.

Prometheus retention is 30 days or 75 GiB, whichever is reached first, leaving space for the WAL and head data in the 100 GiB claim. Prometheus spells this binary unit `75GB` in its configuration. Alloy's volume reserves space for future component state/write queues; no queue exists until a pipeline is configured. Grafana persists its SQLite database, users, and plugins.

Combined requests are 475 millicores and 1,440 MiB; limits are 2 CPU and 3,712 MiB. Adjust after collection is enabled and actual usage is available.

## Access and Credentials

The Grafana Route uses edge TLS with the cluster wildcard certificate and redirects HTTP to HTTPS. Anonymous access and sign-up are disabled. External Secrets generates a 48-character initial admin password once and retains the Secret independently of the ExternalSecret. No Bitwarden entry is required for this phase.

After GitOps deployment, retrieve the initial password and sign in as `admin`:

```bash
oc get secret grafana-admin -n monitoring -o jsonpath='{.data.password}' | base64 --decode
```

Store the password in Bitwarden. This secret bootstraps the database only: editing or regenerating it does not rotate an existing Grafana user's password. Change that password through Grafana. A later display account should have the Viewer role.

NetworkPolicy permits router access to Grafana on port 3000. All other pod ingress is denied, including access from other pods in this namespace. Backend Services are ClusterIP only and can be inspected by an authorized administrator using port forwarding. No backend is exposed through a Route. Egress is unchanged; a later collection change must add explicit ingress rules between the intended clients and backends.

ConfigMaps have Kustomize-generated hashes, so configuration changes roll the associated Deployment through GitOps. Images use explicit release tags and are covered by the repository's Renovate configuration.

## Validation and Rollout

Render locally before review:

```bash
kustomize build kubernetes/ocp-mgmt/applications/monitoring
```

Commit only after human review and leave the push to the human. After the approved commit is pushed, let Argo CD reconcile it; do not apply local manifests or create test Jobs for validation.

Run these read-only checks after reconciliation:

```bash
oc get application monitoring -n openshift-gitops
oc get externalsecret grafana-admin -n monitoring
oc get pods,pvc,services,route -n monitoring -o wide
oc rollout status deployment/grafana -n monitoring
oc rollout status deployment/prometheus -n monitoring
oc rollout status deployment/alloy -n monitoring
oc rollout status deployment/blackbox-exporter -n monitoring
curl --fail --silent --show-error https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/api/health
```

Confirm all claims are Bound to local NVMe, pods run on `ms-02` or `ms-04`, Grafana login works, and its data-source list is empty. In a separate terminal, forward Prometheus:

```bash
oc port-forward -n monitoring service/prometheus 9090:9090
```

Then verify both the target list and stored series are empty:

```bash
curl --fail --silent --show-error http://localhost:9090/api/v1/targets
curl --fail --silent --show-error --get http://localhost:9090/api/v1/query --data-urlencode 'query=count({__name__=~".+"})'
```

Expected results are empty `activeTargets`, `droppedTargets`, and query `result` arrays. Alloy's `/-/ready` and Blackbox Exporter's `/-/healthy` endpoints can likewise be checked through port forwarding to ports 12345 and 9115; do not invoke `/probe` during this phase. PVC mount permissions, image startup, Route access, and persistence across a subsequent GitOps rollout must be verified after deployment.

## Later Collection Phase

Add Grafana data sources, scoped backend NetworkPolicy rules, OpenShift read-only monitoring identities with token renewal, and infrastructure collection in a separate reviewed change. Enable Prometheus's remote-write receiver only when a defined Alloy pipeline needs it. Keep SNMP targets, credentials, and reachability targets out of this foundation. Loki and log collection are outside this phase.

References: [Grafana configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/), [Prometheus retention](https://prometheus.io/docs/prometheus/latest/storage/), [Alloy health endpoints](https://grafana.com/docs/alloy/latest/reference/http/).
