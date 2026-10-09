# Media Services

The [Media Services dashboard](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/media-services) queries the existing `ocp-home` Thanos data source for pod resources and `infrastructure` for [Tautulli stream counts, library inventory, and bandwidth estimates](../tautulli/README.md), [SAB queue metrics](../sabnzbd/README.md), and QNAP media-share capacity. Workload GitOps remains in [homelab-private](https://github.com/morey-tech/homelab-private/tree/main/kubernetes/ocp-home/applications); this repository owns collection and Grafana provisioning.

## Graphs

Three playback-count cards, SAB remaining download work, and a `qnap-01` media-share gauge occupy the top left, with stream history at the top right. The next row aligns Plex CPU, memory, and WAN/LAN bandwidth estimates. The bottom row contains SAB CPU, memory, and download speed, followed by episode and movie count cards. Shared host network traffic is no longer shown here. The visible dashboard still ends at grid row 19, preserving its previous screen footprint. **Secondary media services** stays collapsed at row 19 with the smaller Sonarr, Radarr, Bazarr, Lidarr, Overseerr, Tautulli, Profilarr, Maintainerr, and Cleanuparr graphs below it.

| Graph | Meaning |
|-------|---------|
| CPU | Five-minute average CPU cores per pod, summed over application containers. One core means one fully utilized CPU core; no CPU limit is assumed. |
| Memory | Working-set bytes per pod, summed over application containers. This includes more than RSS and is not a percentage of a limit. |
| Secondary service network | Five-minute receive/transmit rates in bits/s from each pod's sandbox interfaces, excluding loopback. Host-network pods are excluded. |
| Plex stream counts | Adjacent current Direct Play, Direct Stream, and Transcoding counts, including paused sessions. Missing, stale, or failed collection displays Unknown rather than the last historical value. |
| Plex stream history | Right-hand graph showing stacked Direct Play, Direct Stream, and Transcoding counts, sampled every 30 seconds. The combined stack height gives total sessions; there is no separate total card or line. |
| Plex bandwidth estimates | WAN and LAN estimates of reserved bandwidth for remote and local Plex sessions, in Mbps, from Tautulli. These are estimates, not measured network traffic. Aligned with Plex CPU and memory graphs. |
| Media share used | Current `(total − free) / total` percentage for `qnap-01` / `storage-media`, with warning at 80% and red at 90%. Logical shared-folder capacity is distinct from pool accounting. Invalid, missing, stale, or failed metrics show Unknown. |
| SAB remaining | Bytes left to download across the whole queue, including queued/paused downloads. Excludes repair, unpacking, and media import. A zero means no remaining download bytes, not necessarily no post-processing. |
| SAB download speed | SAB application download speed history, sampled every 30 seconds. API KiB/s is converted to bytes/s; this measures downloads, not total host traffic. |
| Episodes / Movies | Current cached inventory from Tautulli: episodes in TV Shows (section 2, including specials) and movies in Movies (section 1). Counts library items, not plays or files. Polled every five minutes; Tautulli cache refresh may add delay. Latest samples are retained for up to 15 minutes; inactive libraries, failed collection, or missing/expired inventory display Unknown. |

Plex uses `hostNetwork: true`: its cAdvisor network counters include host interfaces and cannot isolate Plex traffic. The Plex bandwidth panel therefore uses Tautulli session estimates. Measured host traffic remains available on the OCP Home dashboard.

Queries select Deployment pods in each app's dedicated namespace and identify each pod in the legend. Parent cgroup and sandbox CPU/memory samples are excluded. Duplicate scrape series are deduplicated before summing; failed or stopped pods are excluded. Pod, activity, and capacity queries require healthy scrapes and samples newer than 180 seconds. Library inventory instead uses the bounded 15-minute cache described above. Missing telemetry appears as gaps, while measured zero remains zero. A restarted pod creates a new line. If a service changes namespace or becomes a StatefulSet, update its selectors.

## Other available pod statistics

Discovery through the existing OCP Home data source confirmed CPU time, memory working set and RSS, network bytes and errors, filesystem read/write counters, container readiness and restarts, and configured resource requests/limits. Requests and limits exist only where configured. CPU throttling series were absent for SABnzbd, which has no CPU limit. Plex session counts come from the separate Tautulli collector; SABnzbd speed and remaining download work come from the separate SAB JSON exporter.

## Validation

Regenerate and validate locally (Python with PyYAML and `promtool` on PATH, or set `PROMTOOL` to its executable):

```bash
python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-media-dashboard.py
python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-media-dashboard.py
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py --local
```

The read-only check retrieves the Grafana admin credential into memory from the management cluster and tests every local panel query against existing telemetry, including six-hour Grafana range queries. It does not provision the dashboard. A stopped application fails its current-data check, even though the dashboard correctly displays a gap.

Before the SAB collector deploys, use `--local --skip-sabnzbd` to check existing pod, QNAP, and Tautulli queries while explicitly deferring the two SAB panels. `--skip-tautulli` is also available for undeployed Tautulli activity and library collectors. These skip flags require `--local`. Historical data begins when each collector deploys; it is not backfilled from the application.

After review, commit, human push, and GitOps reconciliation, verify the provisioned dashboard:

```bash
python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py
```

Open the dashboard to check layout, legends, Plex bandwidth alignment, and library count cards. Its dedicated generated ConfigMap is projected into Grafana's existing dashboard directory.

Validation covers synthetic query scenarios, non-overlap/unique-ID checks, and the unchanged 19-row visible footprint. Library cases cover sparse polling, correct item hierarchy, valid zero counts, failed scrapes, inactive libraries, and missing or expired inventory. Provisioned-dashboard comparison and visual review remain post-GitOps checks.
