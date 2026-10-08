# Tautulli stream collection

The `tautulli-exporter` Deployment runs the [Prometheus JSON exporter](https://github.com/prometheus-community/json_exporter) v0.8.0 on OCP Management. Alloy probes it every 30 seconds with a 20-second scrape timeout and forwards the four aggregate gauges into infrastructure Prometheus (`job="tautulli", instance="plex"`). It requests `get_activity` from [Tautulli](https://tautulli.apps.ocp-home.rh-lab.morey.tech/home) over verified HTTPS.

| Metric | API field |
|--------|-----------|
| `tautulli_streams` | `stream_count` |
| `tautulli_streams_direct_play` | `stream_count_direct_play` |
| `tautulli_streams_direct_stream` | `stream_count_direct_stream` |
| `tautulli_streams_transcode` | `stream_count_transcode` |

Counts represent current sessions, including paused sessions, rather than only sessions actively playing. No user names, media titles, or session identifiers are exported. Historical metrics begin at deployment and use infrastructure Prometheus retention; existing Tautulli history is not imported.

## Authentication and access

External Secrets reads the password of Bitwarden login item `aef8aa11-b859-457f-b1e3-b4dd01844a86` into `tautulli-api-v1/api-key`, refreshing hourly. The exporter reads the projected file for the `X-Api-Key` header on each request, supporting rotation without a restart after Secret propagation. Tautulli 2.18.0+ supports this header; the discovered instance runs 2.18.2. The key is not included in the target URL, Alloy config, or dashboard. Redirects are disabled.

Only Alloy pods in `monitoring` may access the exporter Service on port 7979. There is no Route. The exporter has no Kubernetes token or persistent storage and runs under `restricted-v2`. A missing Secret blocks only this exporter. No changes to the private media GitOps repository are required.

HTTP failures fail the scrape; missing or invalid JSON fields produce no corresponding gauge. A successful scrape with absent fields is therefore not proof of valid activity data. Consumers must require both fresh gauges and a successful scrape. Zero is valid only when explicitly returned by Tautulli.

## Validation and rollout

Test the exact release locally using its `json_exporter` executable and Python with PyYAML:

```bash
JSON_EXPORTER=/tmp/tautulli-validation/json_exporter-0.8.0.linux-amd64/json_exporter \
  python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-tautulli.py
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

The fixture test covers header authentication, numeric/string counts, zero sessions, API errors, missing fields, HTTP failures, and credential-file rotation. It uses only fake credentials and local loopback servers.

After review, commit, human push, and GitOps reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret tautulli-api-v1
oc --context=logged-user -n monitoring rollout status deployment/tautulli-exporter
oc --context=logged-user -n monitoring rollout status deployment/alloy
```

Verify all four gauges and `up{job="tautulli",instance="plex"}` in Grafana's infrastructure data source. Exporter `/metrics` readiness checks only the exporter process; it does not confirm Tautulli authentication or Plex connectivity. The API credential, cluster network path, Secret reconciliation, and ongoing collection must be checked after deployment.
