# Tautulli collection

The `tautulli-exporter` Deployment runs the [Prometheus JSON exporter](https://github.com/prometheus-community/json_exporter) v0.8.0 on OCP Management. Alloy probes read-only [Tautulli](https://tautulli.apps.ocp-home.rh-lab.morey.tech/home) APIs over verified HTTPS through the exporter and forwards metrics to infrastructure Prometheus. All jobs use `instance="plex"`. Activity remains on `job="tautulli"` so existing dashboards continue to work.

| Job | API command | Interval | Timeout |
|-----|-------------|----------|---------|
| `tautulli` | `get_activity` | 30 seconds | 20 seconds |
| `tautulli_connection` | `server_status` | 60 seconds | 20 seconds |
| `tautulli_libraries` | `get_libraries` | 5 minutes | 30 seconds |
| `tautulli_server` | `get_server_info` | 5 minutes | 20 seconds |

| Metric | API field |
|--------|-----------|
| `tautulli_streams` | `stream_count` |
| `tautulli_streams_direct_play` | `stream_count_direct_play` |
| `tautulli_streams_direct_stream` | `stream_count_direct_stream` |
| `tautulli_streams_transcode` | `stream_count_transcode` |
| `tautulli_wan_bandwidth_kilobits_per_second` | `wan_bandwidth` |
| `tautulli_lan_bandwidth_kilobits_per_second` | `lan_bandwidth` |
| `tautulli_total_bandwidth_kilobits_per_second` | `total_bandwidth` |
| `tautulli_plex_connected` | `connected` (1/0) |
| `tautulli_library_items` | `count` |
| `tautulli_library_parents` | `parent_count` |
| `tautulli_library_children` | `child_count` |
| `tautulli_library_active` | `is_active` (1/0) |
| `tautulli_plex_pass` | `pms_plexpass` (1/0), with `version` and `platform` labels |

Counts represent current sessions, including paused sessions, rather than only sessions actively playing. No user names, media titles, or session identifiers are exported. Historical metrics begin at deployment and use infrastructure Prometheus retention; existing Tautulli history is not imported.

WAN bandwidth is Plex's estimated reserved bandwidth for remote sessions in **kbps**, not measured traffic. The dashboard divides by 1000 to display **Mbps**. The value is a gauge, so no rate calculation is applied. Missing data stays unknown; an explicit zero means no estimated WAN demand. [Tautulli source](https://github.com/Tautulli/Tautulli/blob/master/plexpy/common.py) documents the field units.

Library gauges use only `section_id` and `type` labels; library names and last-played titles are not exported. Item/parent/child counts describe a hierarchy, not disjoint totals: movies use items; television libraries use shows/seasons/episodes; music libraries use artists/albums/tracks. Null or unavailable levels are omitted rather than exported as zero. `get_libraries` returns the whole cached inventory without pagination; it does not trigger a library scan. Counts can decrease when media is removed, so these are gauges, not counters.

Plex connection status measures Tautulli's reported connection to Plex. A failed scrape is unknown, not disconnected. Plex Pass and version/platform metadata describe configuration; they do not prove Plex is reachable. Use the connection job for that.

Only the WAN estimate is added to the current dashboard. The other metrics are collected for future bandwidth, availability, inventory-growth, and upgrade panels. Session-state counts and hardware-transcoding counts require aggregation of individual sessions beyond this JSON exporter configuration; they remain uncollected.

## Querying slow metrics

For five-minute library/server jobs, do not reuse the activity dashboard's 180-second freshness cutoff. Use a lookback and explicit freshness allowance that accommodate their cadence, such as 15 minutes. Otherwise instant queries can show gaps before the next scrape, even when collection is healthy. For example, current library item counts guarded by successful recent collection:

```promql
last_over_time(tautulli_library_items{job="tautulli_libraries"}[15m])
and on(job, instance)
(last_over_time(up{job="tautulli_libraries"}[15m]) == 1)
```

Check missing metric series as well as `up`: a successful HTTP response without the expected data produces no corresponding gauge. Seven activity series, one connection series, library-dependent inventory series, and one server-metadata series were observed during discovery (19 total for the three current libraries).

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

The fixture test covers all four modules: header authentication, numeric/string counts and bandwidth, zero sessions, invalid/missing values, boolean connection states, multiple library types and null hierarchy levels, version labels, API/HTTP failures, and credential-file rotation. It uses only fake credentials and local loopback servers.

After review, commit, human push, and GitOps reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret tautulli-api-v1
oc --context=logged-user -n monitoring rollout status deployment/tautulli-exporter
oc --context=logged-user -n monitoring rollout status deployment/alloy
```

Verify the documented gauges and `up{job=~"tautulli.*",instance="plex"}` in Grafana's infrastructure data source. Exporter `/metrics` readiness checks only the exporter process; it does not confirm Tautulli authentication or Plex connectivity. The API credential, cluster network path, Secret reconciliation, and ongoing collection must be checked after deployment.
