# SABnzbd Queue Metrics

SABnzbd 5.1.3 runs on OCP Home. A dedicated JSON exporter on OCP Management reads aggregate queue metrics from [its API](https://sabnzbd.apps.ocp-home.rh-lab.morey.tech/api). Alloy polls the exporter every 30 seconds with a 20-second deadline and writes `job="sabnzbd",instance="sabnzbd"` to infrastructure Prometheus.

## Credentials and API

Bitwarden Login item `e1126683-318a-4b75-bb41-b4de0116104f` stores the **full API key** in its password field, not the add-only NZB key. External Secrets creates `sabnzbd-api-v1` in `monitoring`. The key is injected into the exporter as `SABNZBD_API_KEY` and encoded into the POST form body at request time. It is absent from scrape URLs, ConfigMaps, and metric labels. TLS verification is enabled and redirects are disabled. Only Alloy can reach the exporter through its ingress NetworkPolicy.

The sole API operation is `mode=queue`, with `limit=1` to limit per-job response data while retaining full-queue aggregates. No job names, identifiers, categories, or passwords are exported. The underlying API key can perform more than reads; the collector only requests the queue. See the [SAB API reference](https://sabnzbd.org/wiki/configuration/5.1/api) and [pinned API implementation](https://github.com/sabnzbd/sabnzbd/blob/5.1.3/sabnzbd/api.py) for units.

Because the key is supplied through an environment variable, changing the Secret alone does not update a running exporter. For rotation, update SAB and Bitwarden, wait for ExternalSecret refresh, then roll the exporter through a reviewed GitOps pod-template change. Do not put the key in a deployment annotation or manually apply local manifests.

## Metrics

| Metric | API field | Meaning |
|--------|-----------|---------|
| `sabnzbd_download_kibibytes_per_second` | `queue.kbpersec` | Current application download speed in KiB/s; dashboard multiplies by 1024 for bytes/s |
| `sabnzbd_queue_remaining_mebibytes` | `queue.mbleft` | Whole-queue remaining download work in MiB; dashboard multiplies by 1048576 for bytes |
| `sabnzbd_queue_jobs` | `queue.noofslots_total` | Total download-queue jobs, regardless of response pagination |
| `sabnzbd_queue_paused` | `queue.paused` | Overall queue paused state: 1 paused, 0 unpaused |

Remaining bytes include queued and paused downloads, but exclude repair, unpacking, and import work. An empty or idle queue can validly report zero. Dashboard queries require fresh nonnegative values and successful scrape health; missing, invalid, or stale data is not treated as zero. The [media dashboard](../media/README.md) shows speed history and current remaining bytes.

## Validation and Rollout

Local fixture tests use the pinned `json_exporter` v0.8.0 binary:

```bash
JSON_EXPORTER=/tmp/media-update/json_exporter-0.8.0.linux-amd64/json_exporter \
  python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-sabnzbd.py
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

Fixtures cover form authentication/escaping, numeric strings, idle and paused queues, missing/invalid values, API error responses, HTTP failures, redirects, and omission of private job data. A read-only probe against SAB 5.1.3 confirmed authentication and the same exporter configuration: the idle queue returned four valid zero metrics. The Bitwarden vault was synced before validating its new item.

After review, commit, human push, and Argo CD reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret sabnzbd-api-v1
oc --context=logged-user -n monitoring rollout status deployment/sabnzbd-exporter
oc --context=logged-user -n monitoring rollout status deployment/alloy
oc --context=logged-user -n monitoring rollout status deployment/grafana
python3.12 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-media.py
```

Exporter reachability from Alloy, deployed scrape health, and visual layout review remain post-deployment checks. No new resources should be applied manually to validate these changes.
