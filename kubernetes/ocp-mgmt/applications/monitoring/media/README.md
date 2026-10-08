# Media Services

The [Media Services dashboard](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/media-services) queries the existing `ocp-home` Thanos data source. Workload GitOps remains in [homelab-private](https://github.com/morey-tech/homelab-private/tree/main/kubernetes/ocp-home/applications); this repository owns Grafana provisioning. No new exporter, credential, or monitoring permissions are required.

## Graphs

Plex and SABnzbd occupy the first two rows with large CPU and memory graphs. One shared host network graph spans those rows. Sonarr, Radarr, Bazarr, Lidarr, Overseerr, Tautulli, Profilarr, Maintainerr, and Cleanuparr follow with smaller graphs, two services per row.

| Graph | Meaning |
|-------|---------|
| CPU | Five-minute average CPU cores per pod, summed over application containers. One core means one fully utilized CPU core; no CPU limit is assumed. |
| Memory | Working-set bytes per pod, summed over application containers. This includes more than RSS and is not a percentage of a limit. |
| Shared host network | OCP Home `bond0` receive/transmit rates in bits/s, averaged over five minutes. Includes Plex, SABnzbd, and all other host traffic; excludes physical bond members to avoid double counting. |
| Secondary service network | Five-minute receive/transmit rates in bits/s from each pod's sandbox interfaces, excluding loopback. Host-network pods are excluded. |

Plex uses `hostNetwork: true`: its cAdvisor network counters include host interfaces and cannot isolate Plex traffic. SABnzbd has dedicated pod counters, but the dashboard intentionally shows the shared host graph once for the two prominent services. Both currently run on the single OCP Home node. Revisit that scope if the cluster expands or their placement changes.

Queries select Deployment pods in each app's dedicated namespace and identify each pod in the legend. Parent cgroup and sandbox CPU/memory samples are excluded. Duplicate scrape series are deduplicated before summing; failed or stopped pods are excluded. Scrape health and samples newer than 180 seconds are required. Missing telemetry appears as gaps, while measured zero remains zero. A restarted pod creates a new line. If a service changes namespace or becomes a StatefulSet, update its selectors.

## Other available pod statistics

Discovery through the existing OCP Home data source confirmed CPU time, memory working set and RSS, network bytes and errors, filesystem read/write counters, container readiness and restarts, and configured resource requests/limits. Requests and limits exist only where configured. CPU throttling series were absent for SABnzbd, which has no CPU limit. Application information such as Plex sessions/transcodes or SABnzbd queue progress needs separate application telemetry.

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

After review, commit, human push, and GitOps reconciliation, verify the provisioned dashboard:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py
```

Open the dashboard to check layout, legends, and shared-host labeling. Its dedicated generated ConfigMap is projected into Grafana's existing dashboard directory.
