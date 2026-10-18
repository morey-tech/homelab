# Hitron modem exporter

The `modem-exporter` Deployment collects bridge-mode telemetry from the Hitron CODA5610Q at `http://192.168.100.1`. Alloy scrapes `modem-exporter.monitoring.svc:9780/metrics` every 60 seconds with `job="modem",instance="hitron"` and forwards it to infrastructure Prometheus. Use Grafana's **Infrastructure** data source to query these metrics. This change does not add dashboard panels or alerts.

## Collection and authentication

[exporter.py](exporter.py) runs on the official Python 3.13 slim image using only the standard library; no runtime package installation or separate image build is required. A generated ConfigMap contains the source. One background worker polls every 60 seconds; HTTP scrapes read its cached result and never cause additional modem requests. The Deployment uses `Recreate` to avoid overlapping login sessions during rollouts.

[External Secrets](../modem-credentials.yaml) reads username and password from Bitwarden Login item `769bd8e4-500b-4cf6-899f-b47c013712b2` through `bitwarden-login`, producing `modem-login-v1`. Both values are mounted as files and read again on the next login, so projected Secret updates do not require an exporter restart. The refresh interval is one hour, after the existing Bitwarden cache has synchronized. Credential values never enter Git, scrape URLs, metric labels, or logs.

The firmware uses `POST /1/Device/Users/Login` with a form-encoded `model` containing JSON. The exporter matches the login page's legacy JavaScript `escape()` encoding, including special and Unicode characters. Status comes from `GET /1/Device/Router/SysInfo`. HTTP 200 can contain the login page: JSON and application status are checked, with at most one login attempt and one status retry per poll. Session cookies remain in memory; valid sessions are reused. The live modem accepted this flow using the specified Bitwarden item, and two consecutive collections required only one login.

HTTP is intentional because the bridge-mode management interface is available that way. The pod's egress policy allows only TCP/80 to `192.168.100.1/32`; proxy discovery and HTTP redirects are disabled. Ingress allows only Alloy on port 9780. There is no Route. The pod uses `restricted-v2`, a read-only root filesystem, dropped capabilities, and no mounted service-account token.

## Metrics and interpretation

| Metric | Meaning |
|--------|---------|
| `hitron_collection_success` | 1 for a successful, fresh modem poll; 0 for authentication, transport, payload, or freshness failure |
| `hitron_last_success_timestamp_seconds` | Last successful collection in Unix seconds; 0 before any success |
| `hitron_collection_duration_seconds` | Duration of the last completed poll |
| `hitron_collection_errors_total` | Failed polls since exporter startup |
| `hitron_login_attempts_total` | Login requests since exporter startup |
| `hitron_interface_uptime_seconds{interface="lan\|wan"}` | Firmware-reported interface uptime; a decrease indicates a reset of that field, not yet proven to be a full modem reboot |
| `hitron_wan_packets_total{direction="receive\|transmit"}` | Firmware-reported WAN packet counters; exact coverage in bridge mode still requires validation |
| `hitron_info{model,firmware,mode}` | Model, software version, and bridge/router mode; value 1 |

Serial numbers, MAC/IP addresses, credentials, and arbitrary API fields are excluded. The formatted `M Bytes`/`G Bytes` totals are omitted because they are rounded and their scaling and bridge-mode coverage have not been verified. Keep using pfSense's exact interface octet counters for throughput. Neither captured page exposed DOCSIS power, SNR/MER, channel lock, corrected/uncorrectable codewords, or event logs; this exporter does not invent those measurements.

Failed polls remove the previous modem telemetry from `/metrics`; stale values are never presented as current successful data. The last-success timestamp and exporter counters remain available. Results also expire after 150 seconds without a completed poll. `/healthz` tracks worker progress, independently of modem availability: an unreachable modem does not cause restart loops. A worker stalled for 180 seconds fails health checks.

`up{job="modem"}` measures Alloy's access to the exporter, while `hitron_collection_success` measures its access to valid modem telemetry. A missing scrape or failed login is not by itself proof of an ISP outage. Compare these metrics with LAN pings, Internet pings, DNS/HTTPS checks, and pfSense WAN counters.

Example Grafana Explore queries:

```promql
hitron_collection_success{job="modem"}
```

```promql
hitron_interface_uptime_seconds{job="modem"}
```

```promql
rate(hitron_wan_packets_total{job="modem"}[5m])
```

## Validation and rollout

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-modem-exporter.py
kustomize build kubernetes/ocp-mgmt/applications/monitoring
```

Tests use a local fake HTTP modem with synthetic credentials. They cover login formatting, cookies, expiry and renewal, failed login, login without an effective session, redirects, credential rotation, stale/failed collection, numeric validation, label escaping, field exclusions, and rendered Secret/ConfigMap wiring. Live read-only status collection with the Bitwarden-backed login was verified from the workspace. Server-side resource validation is non-persisting; the exporter has not been deployed as part of these checks.

After review, approved commits, human push, and Argo CD reconciliation:

```bash
oc -n monitoring get externalsecret modem-login-v1
oc -n monitoring rollout status deployment/modem-exporter
oc -n monitoring rollout status deployment/alloy
oc -n monitoring logs deployment/modem-exporter --tail=30
oc -n monitoring port-forward service/prometheus 19090:9090
```

In another terminal:

```bash
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=up{job="modem"}'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=hitron_collection_success{job="modem"}'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=hitron_interface_uptime_seconds{job="modem"}'
```

Confirm Secret synchronization, image startup under the assigned UID, egress to the modem from the scheduled monitoring node, stable session reuse, and fresh samples in Prometheus. Actual new-ServiceAccount admission, NetworkPolicy enforcement, and end-to-end collection remain deployment checks. Observe natural modem reconnects to establish uptime reset semantics; do not deliberately disrupt the WAN for validation.
