# Media Services

The [Media Services dashboard](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/media-services) queries the existing `ocp-home` Thanos data source for pod resources and `infrastructure` for [Tautulli stream counts and bandwidth estimates](../tautulli/README.md), [SAB queue metrics](../sabnzbd/README.md), and QNAP media-share capacity. Workload GitOps remains in [homelab-private](https://github.com/morey-tech/homelab-private/tree/main/kubernetes/ocp-home/applications); this repository owns collection and Grafana provisioning.

## Graphs

Three playback-count cards, SAB remaining download work, and a `qnap-01` media-share gauge occupy the top left. The right column keeps stream history, shared host traffic, and Plex WAN/LAN bandwidth estimates in panels of 7, 6, and 6 grid units. Plex CPU/memory remain below the cards. SAB CPU/memory are narrower to fit a download-speed graph beside them. The visible dashboard still ends at grid row 19, preserving its previous screen footprint. **Secondary media services** stays collapsed at row 19 with the smaller Sonarr, Radarr, Bazarr, Lidarr, Overseerr, Tautulli, Profilarr, Maintainerr, and Cleanuparr graphs below it.

| Graph | Meaning |
|-------|---------|
| CPU | Five-minute average CPU cores per pod, summed over application containers. One core means one fully utilized CPU core; no CPU limit is assumed. |
| Memory | Working-set bytes per pod, summed over application containers. This includes more than RSS and is not a percentage of a limit. |
| Shared host network | OCP Home `bond0` receive/transmit rates in bits/s, averaged over five minutes. Includes Plex, SABnzbd, and all other host traffic; excludes physical bond members to avoid double counting. |
| Secondary service network | Five-minute receive/transmit rates in bits/s from each pod's sandbox interfaces, excluding loopback. Host-network pods are excluded. |
| Plex stream counts | Adjacent current Direct Play, Direct Stream, and Transcoding counts, including paused sessions. Missing, stale, or failed collection displays Unknown rather than the last historical value. |
| Plex stream history | Right-hand graph showing stacked Direct Play, Direct Stream, and Transcoding counts, sampled every 30 seconds. The combined stack height gives total sessions; there is no separate total card or line. |
| Plex bandwidth estimates | WAN and LAN estimates of reserved bandwidth for remote and local Plex sessions, in Mbps, from Tautulli. These are estimates, not measured network traffic. Replaces the media dashboard's pfSense WAN graph; pfSense collection continues for its own dashboard. |
| Media share used | Current `(total − free) / total` percentage for `qnap-01` / `storage-media`, with warning at 80% and red at 90%. Logical shared-folder capacity is distinct from pool accounting. Invalid, missing, stale, or failed metrics show Unknown. |
| SAB remaining | Bytes left to download across the whole queue, including queued/paused downloads. Excludes repair, unpacking, and media import. A zero means no remaining download bytes, not necessarily no post-processing. |
| SAB download speed | SAB application download speed history, sampled every 30 seconds. API KiB/s is converted to bytes/s; this is separate from shared host traffic. |

Plex uses `hostNetwork: true`: its cAdvisor network counters include host interfaces and cannot isolate Plex traffic. SABnzbd has dedicated pod counters, but the dashboard intentionally shows the shared host graph once for the two prominent services. Both currently run on the single OCP Home node. Revisit that scope if the cluster expands or their placement changes.

Queries select Deployment pods in each app's dedicated namespace and identify each pod in the legend. Parent cgroup and sandbox CPU/memory samples are excluded. Duplicate scrape series are deduplicated before summing; failed or stopped pods are excluded. Scrape health and samples newer than 180 seconds are required. Missing telemetry appears as gaps, while measured zero remains zero. A restarted pod creates a new line. If a service changes namespace or becomes a StatefulSet, update its selectors.

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

Before the SAB collector deploys, use `--local --skip-sabnzbd` to check existing pod, host, QNAP, and Tautulli queries while explicitly deferring the two SAB panels. `--skip-tautulli` is also available for an undeployed Tautulli collector. These skip flags require `--local`. Historical data begins when each collector deploys; it is not backfilled from the application.

After review, commit, human push, and GitOps reconciliation, verify the provisioned dashboard:

```bash
python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py
```

Open the dashboard to check layout, legends, and shared-host labeling. Its dedicated generated ConfigMap is projected into Grafana's existing dashboard directory.

Validation for this layout passed 58 synthetic query scenarios, non-overlap/unique-ID checks, and the unchanged 19-row visible footprint. Existing-source queries passed current and six-hour Grafana checks. SAB passed a live API/exporter probe and local failure/idle/paused fixtures. Deployed SAB queries and visual review remain post-GitOps checks.
