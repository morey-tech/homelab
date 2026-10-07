# Monitoring

Grafana, infrastructure Prometheus, Grafana Alloy, and Blackbox Exporter are hosted in the `monitoring` namespace on `ocp-mgmt`. The application ApplicationSet explicitly enables this directory.

The [Homelab Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/homelab-overview) combines CPU and memory graphs for OCP Home, OCP Management, and QNAP, plus RTX 3090 GPU utilization on `tr-gpu`. Each system has a column with CPU above memory; the GPU graph spans the bottom row. Cluster graphs show one line per node, and QNAP shows `qnap-01`. All seven panels use percentage scales, a shared six-hour window, and a 30-second dashboard refresh (QNAP samples arrive every 60 seconds). Missing telemetry appears as gaps. The dashboard reuses the existing data sources and guarded queries; it does not copy cluster metrics into infrastructure Prometheus. Use the **Homelab dashboards** dropdown to open the detailed dashboards, or append `?kiosk` for a wall display.

Regenerate the shared overview after changing a source dashboard's utilization queries:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-overview-dashboard.py
```

Grafana queries the existing `ocp-mgmt` Thanos Querier through the provisioned **OCP Management** data source. The [OCP Management Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/ocp-mgmt-overview) dashboard shows node readiness, CPU and memory, operator health, active alerts, and the existing DCGM metrics for the RTX 3090 on `tr-gpu`. It refreshes every 30 seconds with a six-hour default window; append `?kiosk` for a wall display.

The **OCP Home** data source queries the remote cluster's existing Thanos HTTPS route. Its [OCP Home Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/ocp-home-overview) uses the same layout and refresh settings for its single node and Intel GPU. Use the **Cluster dashboards** dropdown to switch clusters. OCP Management remains the default data source.

Cluster metrics remain in OpenShift's monitoring stack, with its existing retention and availability. Alloy collects QNAP metrics over SNMPv3 and forwards them to infrastructure Prometheus through its internal remote-write receiver. The **Infrastructure** data source serves the [QNAP Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/qnap-overview) dashboard. Prometheus has no direct scrape jobs or recording rules. Blackbox Exporter defines HTTP and TCP modules but has no callers or targets.

## OCP Management Metrics

The data source uses `https://thanos-querier.openshift-monitoring.svc:9091` with certificate and hostname verification. OpenShift injects the service CA into the dedicated `grafana-service-ca` ConfigMap. The dedicated `monitoring/ocp-mgmt-metrics` service account has only `get` on `prometheuses/api` named `k8s` in `openshift-monitoring`, via [a namespaced Role and RoleBinding](../../system/openshift-monitoring/grafana-metrics-rbac.yaml). Grafana is configured to send GET requests; no cluster-wide monitoring role or API write permission is granted.

The token controller populates `ocp-mgmt-metrics-token-v1`. Grafana reads the token and CA through environment references at startup and provisions them as secure data-source fields. No token or CA value is embedded in Git or dashboard JSON. The Grafana pod's own service account still has no monitoring permission and automatic token mounting remains disabled.

ESO generates a separate, stable `grafana-encryption-key` Secret for Grafana's stored credentials. Preserve and back up this key together with the Grafana database; recreating it can make stored encrypted settings unreadable. This phase introduces the key before the first data-source credential is provisioned. If encrypted integrations have been added manually since the foundation deployed, migrate their encryption before changing the key.

Both the `monitoring` and `openshift-monitoring-system` Argo CD Applications must sync this change. They reconcile independently; queries may return 403 until the RoleBinding exists. The platform's existing NetworkPolicy permits authenticated access to Thanos on port 9091, and Grafana already has outbound access. Cluster data-source queries do not pass through infrastructure Prometheus.

### Dashboard Status

| State | Meaning |
|-------|---------|
| Healthy | All expected nodes Ready (4 for management, 1 for home), no unavailable/degraded/failing operators, no critical/warning alerts or progressing operators |
| Attention | Warning alerts or progressing operators |
| Unhealthy | Missing/unready expected nodes, unavailable/degraded/failing operators, or critical alerts |
| Unknown | Required monitoring sources or Watchdog missing, down, or older than 180 seconds; a query error must also be treated as unknown |

Expected management nodes are `ms-02`, `ms-03`, `ms-04`, and `tr-gpu`; OCP Home expects `ocp-home-01.rh-lab.morey.tech`. The health definition uses each cluster's expected node count (4 or 1). Edit `CLUSTERS` in [the dashboard generator](scripts/build-dashboard.py) when topology changes. The kube-state-metrics **main** endpoint, cluster-version-operator, Prometheus self-scrape, and always-firing Watchdog alert guard the cluster status. Absent warning/critical alert series become zero only when those sources are present. GPU panels show Unknown for missing, down, or stale telemetry. Empty alert/operator tables indicate no problems only when the summary has known data.

### Token and CA Rotation

This is a manually managed, long-lived service-account token, following the repository's current credential pattern. It does not expire automatically. Review/rotate it at least every 90 days and immediately if exposed. This avoids copying an expiring projected token into Grafana's persistent data-source configuration without a refresh mechanism.

To rotate through GitOps, change the Secret name in `ocp-mgmt-credentials.yaml` and the matching Grafana environment reference in `grafana.yaml` from `ocp-mgmt-metrics-token-v1` to the next version. Submit both changes for review, commit after approval, and have the human push. Argo CD creates the replacement token, recreates Grafana, and prunes the old Secret, revoking the old token. A brief interruption during reconciliation is expected. Run the verification below after sync. Do not edit token values or delete the live Secret manually.

CA injection updates the ConfigMap automatically, but Grafana's environment and provisioned CA refresh only when its pod is replaced. After service CA rotation, make a reviewed change to the Grafana pod-template annotation `homelab.morey.tech/service-ca-revision` (add it if absent), then push and let GitOps recreate the pod while the old/new CA overlap is available. Never work around a certificate error by disabling TLS verification. A projected-token integration with automatic refresh can replace this manual lifecycle later.

## OCP Home Metrics

The data source connects to `https://thanos-querier-openshift-monitoring.apps.ocp-home.rh-lab.morey.tech` on port 443 over the existing private network. The publicly trusted Route certificate is verified using Grafana's system trust store. No extra CA, Tailscale identity, proxy, or OpenShift API credential is added to Grafana.

[OCP Home's metrics component](../../../ocp-home/system/openshift-monitoring/README.md) owns the dedicated `openshift-monitoring/grafana-ocp-mgmt` service account, versioned token Secret, and namespaced GET-only Role. Management External Secrets reads the token from the password field of Bitwarden login item `762ec6ea-79b5-4e9f-be81-b4dc014da106` into `ocp-home-metrics-token-v1`, refreshing hourly. Grafana consumes that Secret at startup and stores the token as an encrypted data-source field.

**Deploy in two stages:** first deploy the OCP Home identity and put its generated token into the Bitwarden item, then deploy the management data source and dashboard. Allow two minutes for the management Bitwarden cache to sync before deploying the consumer. A missing credential can block Grafana startup; an empty password produces authentication errors. The source README includes exact token retrieval, verification, and rotation steps. No token is transferred or resource applied manually by this repository change.

The dashboard shows readiness for one node, CPU/memory, operator health, warning/critical alerts, and existing Intel iGPU render usage, video-engine-0 usage, frequency, and GPU-only power. Existing alerts are displayed without filtering out cluster problems. If the remote monitoring data disappears, status becomes Unknown or the panel reports a query error; zero metrics must not be interpreted as healthy. Cluster history remains subject to OCP Home's retention and availability.

## QNAP Metrics

[QNAP collection details](qnap/README.md) cover the supplied QuTS hero MIB, SNMPv3 credentials, capacity semantics, and validation. Alloy polls `192.168.6.20:161` every 60 seconds using HMAC-SHA and CBC-DES (`authPriv`). External Secrets reads Bitwarden item `29df3066-0d03-464d-bf35-b4dc017a372e`; Alloy watches the mounted Secret so credential updates do not require a restart.

Only Alloy and Grafana pods in this namespace may connect to infrastructure Prometheus on port 9090. The NetworkPolicy controls pods and ports, not HTTP paths: either allowed client can reach the receiver and query API. Prometheus has no external Route. Alloy's own API remains ingress-denied, and its existing egress policy permits polling the NAS.

The dashboard shows collection status, uptime, CPU/memory, pool and share capacity, and disk/RAID/hardware health. Pool and share accounting remain separate; absent or stale samples are not treated as healthy. QNAP's Secret is required only by Alloy, so a credential provisioning failure does not block Grafana or its cluster dashboards.

## Services and Storage

| Service | Image version | Storage | Access |
|---------|---------------|---------|--------|
| Grafana | 13.2.3 | 5 GiB | [grafana.apps.ocp-mgmt.rh-lab.morey.tech](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech) |
| Prometheus | 3.15.0 | 100 GiB | `prometheus.monitoring.svc:9090` |
| Alloy | 1.20.1 | 5 GiB | `alloy.monitoring.svc:12345` |
| Blackbox Exporter | 0.29.0 | None | `blackbox-exporter.monitoring.svc:9115` |

All persistent volumes use `lvms-vg-nvme`. Required node affinity limits every workload to `ms-02` or `ms-04`; `ms-03` has no configured NVMe volume group, and `tr-gpu` is reserved for other workloads. OpenShift assigns the UID and volume group through the explicitly required `restricted-v2` SCC; no fixed UID, privileged init container, host mount, or extra SCC is required.

Each Deployment has one replica. Recreate updates release each ReadWriteOnce volume before starting its replacement. Volumes are node-local and are not replicated: loss of a storage node takes its service offline until the node recovers or data is restored. PVC annotations require confirmation before Argo CD pruning and preserve claims when the Application is deleted. The storage class has a Delete reclaim policy, so manually deleting a PVC can still destroy its data.

Prometheus retention is 30 days or 75 GiB, whichever is reached first, leaving space for the WAL and head data in the 100 GiB claim. Prometheus spells this binary unit `75GB` in its configuration. Alloy uses its volume for the remote-write WAL, buffering infrastructure samples when Prometheus is temporarily unavailable. Grafana persists its SQLite database, users, and plugins.

Combined requests are 475 millicores and 1,696 MiB; limits are 2 CPU and 4,224 MiB. Grafana requests 512 MiB with a 1 GiB limit after the first dashboard rollout exceeded its previous 512 MiB limit; observed usage after restart was about 409 MiB. Adjust from observed usage as data sources and dashboards grow.

## Access and Credentials

The Grafana Route uses edge TLS with the cluster wildcard certificate and redirects HTTP to HTTPS. Anonymous access and sign-up are disabled. External Secrets generates a 48-character initial admin password once and retains the Secret independently of the ExternalSecret. The Grafana admin credential does not depend on Bitwarden; the OCP Home data-source credential does.

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
kustomize build kubernetes/ocp-home/system/openshift-monitoring
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-dashboard.py
```

The tests require Python 3.12+, PyYAML, and `promtool` on PATH. They exercise both cluster topologies, including healthy, warning, critical, missing/unready nodes, operator failure/progression, failed sources, missing Watchdog, stale/absent metrics, and literal DNS-name matching. They also check that both committed dashboards match the generator and use the correct data source. Edit the generator and regenerate both JSON files together.

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
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-cluster.py
```

The read-only script uses the generated Grafana admin password in memory from the `logged-user` management context, verifies both provisioned data sources and dashboards, and queries through Grafana's proxy and panel-plugin endpoints. Use `--cluster ocp-mgmt` or `--cluster ocp-home` to check one cluster. Set `GRAFANA_PASSWORD` in the environment if the initial admin password has been changed. Confirm visually that the management overview has four node series, the home overview has one, and each has its respective GPU telemetry without panel errors. These checks require the approved changes to have deployed through GitOps.

Infrastructure Prometheus receives QNAP samples from Alloy. In a separate terminal, forward it:

```bash
oc port-forward -n monitoring service/prometheus 9090:9090
```

Then verify the direct target list and the QNAP collection status:

```bash
curl --fail --silent --show-error http://localhost:9090/api/v1/targets
curl --fail --silent --show-error --get http://localhost:9090/api/v1/query --data-urlencode 'query=up{job="qnap",instance="qnap-01"}'
```

Expected results are empty `activeTargets` and `droppedTargets` arrays (scraping runs in Alloy), and a QNAP `up` result of `1`. An empty query result or `0` requires investigation; allow two scrape intervals after rollout. Alloy's `/-/ready` and Blackbox Exporter's `/-/healthy` endpoints can likewise be checked through port forwarding to ports 12345 and 9115; do not invoke `/probe` during this phase. PVC mount permissions, image startup, Route access, and persistence across a subsequent GitOps rollout must be verified after deployment.

## Later Collection Phases

Add other NAS devices, reachability targets, network devices, Loki, and log collection in separate reviewed changes. QNAP is currently the only infrastructure collection target.

References: [Grafana configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/), [Prometheus retention](https://prometheus.io/docs/prometheus/latest/storage/), [Alloy health endpoints](https://grafana.com/docs/alloy/latest/reference/http/).
