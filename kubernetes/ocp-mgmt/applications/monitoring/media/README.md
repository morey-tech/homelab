# Media Services

The [Media Services dashboard](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/media-services) queries the existing `ocp-home` Thanos data source for pod resources and `infrastructure` for [Tautulli stream counts and WAN estimates](../tautulli/README.md). Workload GitOps remains in [homelab-private](https://github.com/morey-tech/homelab-private/tree/main/kubernetes/ocp-home/applications); this repository owns collection and Grafana provisioning.

## Graphs

Four stream-count cards and a WAN estimate card occupy the top left. Stacked stream history sits at the top right, two grid units taller than the cards. Plex and SABnzbd CPU and memory graphs start immediately below the cards. The right column stacks stream history, shared host traffic, and WAN traffic in panels of 7, 6, and 6 grid units, fitting above the collapsed secondary section. Below them are Sonarr, Radarr, Bazarr, Lidarr, Overseerr, Tautulli, Profilarr, Maintainerr, and Cleanuparr with smaller graphs, two services per row, inside **Secondary media services**, collapsed by default. Expand that section to view them; Plex, SABnzbd, shared host traffic, and stream counts/history remain visible.

| Graph | Meaning |
|-------|---------|
| CPU | Five-minute average CPU cores per pod, summed over application containers. One core means one fully utilized CPU core; no CPU limit is assumed. |
| Memory | Working-set bytes per pod, summed over application containers. This includes more than RSS and is not a percentage of a limit. |
| Shared host network | OCP Home `bond0` receive/transmit rates in bits/s, averaged over five minutes. Includes Plex, SABnzbd, and all other host traffic; excludes physical bond members to avoid double counting. |
| Secondary service network | Five-minute receive/transmit rates in bits/s from each pod's sandbox interfaces, excluding loopback. Host-network pods are excluded. |
| Plex stream counts | Adjacent current Total, Direct Play, Direct Stream, and Transcoding counts, including paused sessions. Missing, stale, or failed collection displays Unknown rather than the last historical value. |
| Plex stream history | Right-hand graph beside the four counts and WAN estimate showing stacked Direct Play, Direct Stream, and Transcoding counts, sampled every 30 seconds. Total is omitted from the graph to avoid counting sessions twice. |
| WAN traffic | Unstacked pfSense WAN upload/download on `ix2` (five-minute averages) alongside the current Plex WAN estimate, all in Mbps. pfSense covers all internet traffic; the Plex estimate is not an attributed subset to subtract or stack. Each source has its own freshness and scrape-health checks. |
| WAN est. | Current Plex estimated reserved bandwidth for remote sessions in Mbps, shown to two decimals. This is not measured WAN traffic. Missing, failed, or stale collection displays Unknown. |

Plex uses `hostNetwork: true`: its cAdvisor network counters include host interfaces and cannot isolate Plex traffic. SABnzbd has dedicated pod counters, but the dashboard intentionally shows the shared host graph once for the two prominent services. Both currently run on the single OCP Home node. Revisit that scope if the cluster expands or their placement changes.

Queries select Deployment pods in each app's dedicated namespace and identify each pod in the legend. Parent cgroup and sandbox CPU/memory samples are excluded. Duplicate scrape series are deduplicated before summing; failed or stopped pods are excluded. Scrape health and samples newer than 180 seconds are required. Missing telemetry appears as gaps, while measured zero remains zero. A restarted pod creates a new line. If a service changes namespace or becomes a StatefulSet, update its selectors.

## Other available pod statistics

Discovery through the existing OCP Home data source confirmed CPU time, memory working set and RSS, network bytes and errors, filesystem read/write counters, container readiness and restarts, and configured resource requests/limits. Requests and limits exist only where configured. CPU throttling series were absent for SABnzbd, which has no CPU limit. Plex session counts come from the separate Tautulli collector; SABnzbd queue progress still needs application telemetry.

## Validation

Regenerate and validate locally (Python with PyYAML and `promtool` on PATH, or set `PROMTOOL` to its executable):

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-media-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-media-dashboard.py
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py --local
```

The read-only check retrieves the Grafana admin credential into memory from the management cluster and tests every local panel query against existing telemetry, including six-hour Grafana range queries. It does not provision the dashboard. A stopped application fails its current-data check, even though the dashboard correctly displays a gap.

Before the Tautulli collector deploys (or while the new WAN metric is pending rollout), use `--local --skip-tautulli` to check pod, host, and pfSense queries while explicitly deferring Tautulli queries, including the estimate within the WAN graph. Stream history starts at collector deployment; it is not backfilled from Tautulli.

After review, commit, human push, and GitOps reconciliation, verify the provisioned dashboard:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py
```

Open the dashboard to check layout, legends, and shared-host labeling. Its dedicated generated ConfigMap is projected into Grafana's existing dashboard directory.
