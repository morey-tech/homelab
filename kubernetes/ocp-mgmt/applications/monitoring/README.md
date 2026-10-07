# Monitoring

Grafana, infrastructure Prometheus, Grafana Alloy, and Blackbox Exporter are hosted in the `monitoring` namespace on `ocp-mgmt`. The application ApplicationSet explicitly enables this directory.

Grafana queries the existing `ocp-mgmt` Thanos Querier through the provisioned **OCP Management** data source. The [OCP Management Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/ocp-mgmt-overview) dashboard shows node readiness, CPU and memory, operator health, active alerts, and the existing DCGM metrics for the RTX 3090 on `tr-gpu`. It refreshes every 30 seconds with a six-hour default window; append `?kiosk` for a wall display.

Cluster metrics remain in OpenShift's monitoring stack, with its existing retention and availability. Infrastructure Prometheus still has no scrape jobs (including itself), discovery, recording rules, remote read/write, or enabled ingestion receivers. Alloy contains only logging configuration. Blackbox Exporter defines HTTP and TCP modules but has no callers or targets. No additional ServiceMonitors, PodMonitors, device credentials, or device integrations are installed.

## OCP Management Metrics

The data source uses `https://thanos-querier.openshift-monitoring.svc:9091` with certificate and hostname verification. OpenShift injects the service CA into the dedicated `grafana-service-ca` ConfigMap. The dedicated `monitoring/ocp-mgmt-metrics` service account has only `get` on `prometheuses/api` named `k8s` in `openshift-monitoring`, via [a namespaced Role and RoleBinding](../../system/openshift-monitoring/grafana-metrics-rbac.yaml). Grafana is configured to send GET requests; no cluster-wide monitoring role or API write permission is granted.

The token controller populates `ocp-mgmt-metrics-token-v1`. Grafana reads the token and CA through environment references at startup and provisions them as secure data-source fields. No token or CA value is embedded in Git or dashboard JSON. The Grafana pod's own service account still has no monitoring permission and automatic token mounting remains disabled.

ESO generates a separate, stable `grafana-encryption-key` Secret for Grafana's stored credentials. Preserve and back up this key together with the Grafana database; recreating it can make stored encrypted settings unreadable. This phase introduces the key before the first data-source credential is provisioned. If encrypted integrations have been added manually since the foundation deployed, migrate their encryption before changing the key.

Both the `monitoring` and `openshift-monitoring-system` Argo CD Applications must sync this change. They reconcile independently; queries may return 403 until the RoleBinding exists. The platform's existing NetworkPolicy permits authenticated access to Thanos on port 9091, and Grafana already has outbound access. No ingress to the idle infrastructure backends is needed.

### Dashboard Status

| State | Meaning |
|-------|---------|
| Healthy | All four expected nodes Ready, no unavailable/degraded/failing operators, no critical/warning alerts or progressing operators |
| Attention | Warning alerts or progressing operators |
| Unhealthy | Missing/unready expected nodes, unavailable/degraded/failing operators, or critical alerts |
| Unknown | Required monitoring sources or Watchdog missing, down, or older than 180 seconds; a query error must also be treated as unknown |

Expected nodes are `ms-02`, `ms-03`, `ms-04`, and `tr-gpu`. Edit `NODES` in [the dashboard generator](scripts/build-dashboard.py) when topology changes. The kube-state-metrics **main** endpoint, cluster-version-operator, Prometheus self-scrape, and always-firing Watchdog alert guard the cluster status. Absent warning/critical alert series become zero only when those sources are present. GPU panels show Unknown for missing, down, or stale telemetry. Empty alert/operator tables indicate no problems only when the summary has known data.

### Token and CA Rotation

This is a manually managed, long-lived service-account token, following the repository's current credential pattern. It does not expire automatically. Review/rotate it at least every 90 days and immediately if exposed. This avoids copying an expiring projected token into Grafana's persistent data-source configuration without a refresh mechanism.

To rotate through GitOps, change the Secret name in `ocp-mgmt-credentials.yaml` and the matching Grafana environment reference in `grafana.yaml` from `ocp-mgmt-metrics-token-v1` to the next version. Submit both changes for review, commit after approval, and have the human push. Argo CD creates the replacement token, recreates Grafana, and prunes the old Secret, revoking the old token. A brief interruption during reconciliation is expected. Run the verification below after sync. Do not edit token values or delete the live Secret manually.

CA injection updates the ConfigMap automatically, but Grafana's environment and provisioned CA refresh only when its pod is replaced. After service CA rotation, make a reviewed change to the Grafana pod-template annotation `homelab.morey.tech/service-ca-revision` (add it if absent), then push and let GitOps recreate the pod while the old/new CA overlap is available. Never work around a certificate error by disabling TLS verification. A projected-token integration with automatic refresh can replace this manual lifecycle later.

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

Configuration and dashboard ConfigMaps have Kustomize-generated hashes, so changes roll the associated Deployment through GitOps. The injected service-CA ConfigMap has a stable name and the rotation procedure above applies to it. Images use explicit release tags and are covered by the repository's Renovate configuration.

## Validation and Rollout

Render locally before review:

```bash
kustomize build kubernetes/ocp-mgmt/applications/monitoring
kustomize build kubernetes/ocp-mgmt/system/openshift-monitoring
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-dashboard.py
```

The tests require Python 3.12+, PyYAML, and `promtool` on PATH. They exercise healthy, warning, critical, missing/unready nodes, operator failure/progression, failed sources, missing Watchdog, and stale/absent metrics, and check that the committed dashboard matches its generator. Edit the generator and regenerate JSON together.

Commit only after human review and leave the push to the human. After the approved commit is pushed, let Argo CD reconcile it; do not apply local manifests or create test Jobs for validation.

Run these read-only checks after reconciliation:

```bash
oc get application monitoring -n openshift-gitops
oc get application openshift-monitoring-system -n openshift-gitops
oc get externalsecret grafana-admin -n monitoring
oc get pods,pvc,services,route -n monitoring -o wide
oc rollout status deployment/grafana -n monitoring
oc rollout status deployment/prometheus -n monitoring
oc rollout status deployment/alloy -n monitoring
oc rollout status deployment/blackbox-exporter -n monitoring
curl --fail --silent --show-error https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/api/health
```

Confirm all claims are Bound to local NVMe and pods run on `ms-02` or `ms-04`. Verify the scoped permission and the Grafana connection:

```bash
oc auth can-i get prometheuses.monitoring.coreos.com/k8s --subresource=api \
  -n openshift-monitoring --as=system:serviceaccount:monitoring:ocp-mgmt-metrics
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-ocp-mgmt.py
```

The read-only script uses the generated Grafana admin password in memory, verifies the provisioned data source and dashboard, and queries through Grafana. Set `GRAFANA_PASSWORD` in the environment if the initial admin password has been changed. Confirm visually that four node series and GPU telemetry appear on the overview, with no panel errors. These checks require the approved changes to have deployed through GitOps.

Infrastructure Prometheus should remain empty. In a separate terminal, forward it:

```bash
oc port-forward -n monitoring service/prometheus 9090:9090
```

Then verify both the target list and stored series are empty:

```bash
curl --fail --silent --show-error http://localhost:9090/api/v1/targets
curl --fail --silent --show-error --get http://localhost:9090/api/v1/query --data-urlencode 'query=count({__name__=~".+"})'
```

Expected results are empty `activeTargets`, `droppedTargets`, and query `result` arrays. Alloy's `/-/ready` and Blackbox Exporter's `/-/healthy` endpoints can likewise be checked through port forwarding to ports 12345 and 9115; do not invoke `/probe` during this phase. PVC mount permissions, image startup, Route access, and persistence across a subsequent GitOps rollout must be verified after deployment.

## Later Collection Phases

Add the OCP Home data source and infrastructure collection in separate reviewed changes. Enable scoped backend NetworkPolicy rules and Prometheus's remote-write receiver only when a defined Alloy pipeline needs them. SNMP targets, device credentials, reachability targets, Loki, and log collection remain outside this phase.

References: [Grafana configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/), [Prometheus retention](https://prometheus.io/docs/prometheus/latest/storage/), [Alloy health endpoints](https://grafana.com/docs/alloy/latest/reference/http/).
