# Internet Quality

[Open Internet Quality](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/internet-quality) after GitOps deployment. The dashboard uses the existing Infrastructure data source, a six-hour default range, UTC timestamps, and a 30-second refresh. It is also listed in the **Homelab dashboards** dropdown.

## Collection

SmokePing Prober sends one IPv4 ICMP echo per second to each target. Alloy scrapes its counters and classic latency histograms every 15 seconds and forwards them to infrastructure Prometheus. The existing Blackbox Exporter runs DNS and HTTPS probes every 15 seconds when called by Alloy. Prometheus evaluates [recording rules](rules.yml) once per minute.

| Target | Address | Purpose |
|--------|---------|---------|
| pfSense | `192.168.6.1` | Local gateway baseline, including the cluster network path |
| Cloudflare | `1.1.1.1` | External ping and direct UDP DNS query for `example.com` A records |
| Google | `8.8.8.8` | External ping and direct UDP DNS query for `example.com` A records |
| Quad9 | `9.9.9.9` | Third independent external ping target |
| Cloudflare HTTPS | [Trace endpoint](https://www.cloudflare.com/cdn-cgi/trace) | TLS and HTTP reachability through cluster DNS |
| Google HTTPS | [Connectivity endpoint](https://www.google.com/generate_204) | Independent TLS and HTTP reachability through cluster DNS |
| Quay registry | [Registry API](https://quay.io/v2/) | OpenShift image-registry dependency; expected 401 plus registry API header |
| Red Hat registry | [Registry API](https://registry.redhat.io/v2/) | Additional cluster dependency; expected 401 plus registry API header |
| Amazon | [robots.txt](https://www.amazon.com/robots.txt) | Small public website response, expected 2xx |
| YouTube | [Connectivity endpoint](https://www.youtube.com/generate_204) | Small public connectivity response, expected 2xx |
| Plex API | [Public features](https://plex.tv/api/v2/features) | Unauthenticated Plex API reachability, expected 2xx |
| Plex web app | [Web client](https://app.plex.tv/desktop/) | Plex web-client delivery, expected 2xx |
| AWS Ireland | [Regional EC2 API](https://ec2.eu-west-1.amazonaws.com/?Action=DescribeRegions&Version=2016-11-15) | `eu-west-1`; expected 400 with `MissingParameter` error |
| AWS Tokyo | [Regional EC2 API](https://ec2.ap-northeast-1.amazonaws.com/?Action=DescribeRegions&Version=2016-11-15) | `ap-northeast-1`; expected 400 with `MissingParameter` error |

The **DNS / HTTPS reachability by target** timeline compares all 12 service checks side by side: reachable, intermittent, failed, or unknown when collection is missing. Existing success, duration, coverage and daily CSV views include the new targets automatically. There are still only four continuous ping targets; the additional data points test outbound application reachability.

These are diverse destinations, not independent votes for an automatic "internet down" verdict. Google and YouTube share a provider; Amazon and both AWS regions share another; Quay/Red Hat and the two Plex checks may have correlated failures. Global websites/CDNs may resolve nearby and do not guarantee geographic separation. The two [documented AWS regional endpoints](https://docs.aws.amazon.com/ec2/latest/devguide/ec2-endpoints.html) provide explicit Ireland/Tokyo destinations; redirects are disabled so a global AWS landing page cannot satisfy them. Region labels describe the selected API region, not a measured physical route. New targets expose `provider` and `region` labels on raw Blackbox metrics; the existing one-minute recording series retain their `target`/`kind` identity for report compatibility.

Quay and Red Hat checks require HTTP 401 and `Docker-Distribution-Api-Version: registry/2.0`, following the [registry API authentication challenge](https://distribution.github.io/distribution/spec/api/). Regional EC2 checks send an unauthenticated, read-only `DescribeRegions` request and require HTTP 400 with `<Code>MissingParameter</Code>` (missing `AWSAccessKeyId`). No account credentials are supplied. These prove endpoint reachability, not successful image pulls, AWS account access, or overall provider health. Plex checks cover its public API and web app, not authenticated playback, remote access, or the local Plex server. No indexers are monitored. HTTP 403/429, unexpected redirects, or a changed API response remain failures to investigate rather than being silently accepted as healthy.

The prober uses literal addresses so name resolution failures cannot stop ping collection. IPv6 is deliberately excluded until its routing and targets are confirmed. No first ISP hop is configured: discovering a responding, useful hop is a separate diagnostic step, and intermediate routers may limit ICMP replies.

Targets are in [smokeping.yml](smokeping.yml) and [config.alloy](../config.alloy). Keep the target dictionaries in [report-internet.py](../scripts/report-internet.py) aligned when adding or removing targets; they make entirely missing targets visible in reports. The test checks ping-target alignment.

## OpenShift execution

The pinned `quay.io/superq/smokeping-prober:v0.12.0` image runs with the OpenShift-assigned UID/group under `restricted-v2`, all capabilities dropped, a read-only root filesystem, and no service-account token. It has no PVC or external Route. Only Alloy can access port 9374; a separate policy allows Alloy to call Blackbox on port 9115. Both use the existing outbound network access. The single prober replica can run on `ms-02` or `ms-04`, following the monitoring workloads' node affinity.

In this version, `protocol: udp` selects pro-bing's unprivileged ICMP socket mode on Linux; the packets on the wire remain ICMP echo. It does **not** test a remote UDP service. The existing Blackbox pod on `ms-04` reports `net.ipv4.ping_group_range = 0 2147483647`, which includes the namespace-assigned group. No `NET_RAW`, custom SCC, host networking, or node sysctl changes are introduced. Confirm actual probe operation after deployment, including after movement to `ms-02`.

The HTTP startup/readiness endpoint checks process availability only. It can stay healthy after a pinger fails. The [liveness check](check-health.sh) retains detection of fatal pinger errors and unavailable/incomplete local metrics, and also detects silent sessions after WAN recovery. During the [October 18 incident](../../../../../docs/incidents/2026-10-18-internet-outage/metadata.json), the original public ping sessions continued to report 100% loss after DNS/HTTPS recovered, while a fresh prober in the same pod received replies. Restarting the prober restored collection; the exact stale-state location was not established.

Every 60 seconds the check compares two local counter snapshots five seconds apart. If an Internet target keeps sending but receives no replies, it starts a separate prober with the same configuration and unprivileged socket mode for ten seconds. A check fails only when that fresh process receives at least five replies from a candidate target while the original process continues sending with **no** replies to that same target throughout the observation. A single stuck target can qualify. Replies from another target or the LAN baseline cannot qualify it. A main-process restart or natural reply recovery cancels that decision; an unavailable diagnostic is inconclusive and does not by itself fail liveness.

Kubernetes restarts the container after **three consecutive failed checks**, normally about two to three minutes after recovery is detectable, plus restart time. During a real outage, fresh probes also fail, so loss continues to be recorded without an outage-induced restart loop. The check targets complete session failure, not intermittent/high packet loss. Fatal pinger errors, broken metrics collection, and check timeouts still fail liveness independently.

The temporary prober listens only on `127.0.0.1:19374` and is never scraped by Alloy. It adds up to roughly ten pings per configured destination per check when confirmation is needed. Its replies do not alter the original counters or historical outage record. The check kills and reaps the temporary process and removes its files on exit. An 8 MiB memory-backed `emptyDir` supplies scratch space while the container root filesystem stays read-only; no extra capabilities, service-account permissions, or public ports are required. The 40-second timeout covers the observation periods and bounded local HTTP reads.

The recording rules separately require actual sending progress and no local send/receive errors. A container restart creates an unknown interval until the rules have complete samples again; it does not rewrite past 100% loss. Check pod events for `Stuck ping session` liveness failures and inspect the per-target counters when investigating a restart. See [Kubernetes probe behavior](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/) for the consecutive-failure restart policy.

## Measurement semantics

- **One-minute loss:** `1 - received_rate / sent_rate`, clamped to 0–1. Four recent scrapes, at least 0.8 sends/second, no counter reset, no socket errors, and a fresh successful collection are required. A stopped or broken collector produces unknown data. Zero replies with continued successful sending produces 100% loss. Delayed replies may cross interval boundaries, so this is an estimate rather than per-packet timeout accounting.
- **Five-minute loss:** the mean of five complete one-minute observations. Missing minutes create gaps.
- **Latency:** histogram estimates of the median and 95th percentile over five minutes, for received replies only. Loss does not become a zero-latency result. Distribution buckets cover 1 ms through 10 s; larger replies enter the overflow bucket. Quantiles are approximate, and p95–p50 spread is not a standardized jitter measurement.
- **DNS/HTTPS success:** mean of four scheduled probe outcomes per minute. A valid failed probe is zero; a failed scrape is unknown. The DNS query requires a nonempty A response with `NOERROR`. All HTTPS checks require successful TLS verification. Website/Plex checks require 2xx; registry and regional API checks require their specific expected authentication/error responses; its duration also includes DNS and application processing.
- **Minute timeline:** less than 5% loss, degraded at 5% or more, unreachable at 99% or more. These are operational thresholds, not an ISP SLA definition.
- **Rolling 24-hour statistics:** means cover observed minutes only. Coverage is valid minutes divided by 1440; low coverage must not be presented as good availability. Coverage starts below 100% during the first day.
- **WAN context:** existing pfSense `ix2` upload/download counters, with the existing freshness guards and five-minute bit rates.

Measurements describe the round-trip path from an OCP pod. They do not establish which direction lost packets or prove the ISP caused the problem. Compare the local gateway, independent external targets, DNS/HTTPS results, and WAN traffic. A simultaneous wired-client or firewall observation helps separate cluster networking from the access link. Collection continues through an internet outage while the local cluster remains healthy; notification delivery over the failed connection is not guaranteed. This change adds no outbound notifications.

Alloy's WAL can buffer samples during a Prometheus interruption, but recording rules do not retroactively evaluate missed minutes. Those intervals remain unknown in the dashboard/report even if raw samples later arrive. Raw counters remain available for manual analysis.

## ISP evidence exports

Start a read-only port-forward in one terminal:

```bash
oc -n monitoring port-forward service/prometheus 19090:9090
```

In another terminal, export the previous seven **completed UTC days**:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/report-internet.py \
  --output /tmp/internet-report
```

Use a new output directory each time. `--start` and `--end` accept ISO dates; start is inclusive and end is exclusive. The script uses Python's standard library and reads only the internal Prometheus query API.

| File | Content |
|------|---------|
| `samples.csv` | Stored one-minute ping-loss and service-success ratios with their original UTC observation timestamps |
| `daily.csv` | Per-target coverage, unknown minutes, mean observed loss/service success, and counts of degraded/unreachable minutes |
| `episodes.csv` | Consecutive observed minutes with at least 5% loss, grouped per ping target; includes first/last observation, count, mean and maximum loss |
| `metadata.json` | Completion marker, reporting dates, targets, thresholds and interpretation notes |

Episodes split at missing minutes and UTC midnight. The observation times and minute counts are approximate evidence of duration, not exact packet-level outage start/end times. A target with no data still has a daily row with 1440 unknown minutes and blank means. If a query fails, the command exits unsuccessfully and leaves no completion marker; do not use that partial directory as a finished report.

For a support case, save these CSVs plus a Grafana screenshot with an absolute time range covering the incident, including the gateway baseline and WAN traffic. Grafana's panel inspector can export the latency series separately. Preserve the files outside the cluster; CSV export is manual, not a scheduled archive.

## Retention

Infrastructure Prometheus retains **180 days or 75 GiB, whichever is reached first**, on its existing 100 GiB node-local PVC. This applies to all infrastructure metrics; OpenShift's separate cluster-monitoring stores are unchanged. The size limit leaves space for the WAL/head and is not a guarantee of six months' history. No additional PVC or replicated storage is introduced.

At implementation, a read-only inspection found about 35 MiB on the Prometheus volume and 2266 active series before these probes were added. Reassess growth after deployment. Node-local storage is not a backup: preserve important reports externally; database recovery requires a separate volume/database backup. Export evidence before retention expires.

## Validation

Run with `promtool`, Alloy and Blackbox versions matching the pinned manifests:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-internet-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-internet.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-internet-health.py
shellcheck kubernetes/ocp-mgmt/applications/monitoring/internet/check-health.sh
promtool check rules kubernetes/ocp-mgmt/applications/monitoring/internet/rules.yml
promtool check config --syntax-only kubernetes/ocp-mgmt/applications/monitoring/prometheus.yml
alloy validate kubernetes/ocp-mgmt/applications/monitoring/config.alloy
blackbox_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/blackbox.yml --config.check
kustomize build kubernetes/ocp-mgmt/applications/monitoring
```

Tests exercise normal traffic, 70% and 100% loss, late replies, missing/failed/stale scrapes, partial windows, stopped sending, local socket errors, restarts/recovery, quantiles, target isolation, WAN interface selection, service failures, and CSV gaps/coverage. The generated JSON must match its generator.

The health-check tests execute the actual shell/AWK scripts with controlled metrics and temporary child processes. They cover genuine outages, partial loss, one/all stuck targets, same-target confirmation, natural recovery, process resets, unavailable diagnostics, fatal errors, malformed metrics, cleanup, and rendered deployment wiring. They do not require cluster access. Following GitOps deployment, verify the scratch mount is writable under the assigned UID, checks fit within their timeout and CPU/memory budget, and no diagnostic process survives a completed check. Observe subsequent real WAN recovery to confirm automatic recovery and preserved outage history; do not intentionally interrupt the WAN or inject faults into the running collector before deployment.

The initial collector rollout was checked with server-side dry runs and a local binary configuration test. For the recovery-check change, local behavioral tests, ShellCheck, Kustomize rendering, and parsing of the incident's real prober metrics passed. Cluster authentication had expired during validation, so server-side admission of the updated template remains unchecked. Actual socket operation, scratch-volume permissions, resource usage, and automatic recovery must be verified after the reviewed change reaches the cluster through GitOps.

After human review, approved commits, human push, and Argo CD reconciliation:

```bash
oc -n monitoring rollout status deployment/smokeping-prober
oc -n monitoring rollout status deployment/alloy
oc -n monitoring rollout status deployment/blackbox-exporter
oc -n monitoring rollout status deployment/prometheus
oc -n monitoring rollout status deployment/grafana
oc -n monitoring logs deployment/smokeping-prober --tail=50
oc -n monitoring exec deployment/smokeping-prober -- cat /proc/sys/net/ipv4/ping_group_range
oc -n monitoring port-forward service/prometheus 19090:9090
```

Using the port-forward, confirm sending progresses, all probe scrapes succeed, and the rules run without errors:

```bash
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=rate(smokeping_requests_total{job="internet_ping"}[1m])'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=up{job=~"internet_ping|internet_services"}'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=smokeping_prober_errors_total'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=internet:ping_loss:ratio1m'
curl -fsS http://127.0.0.1:19090/api/v1/rules
curl -fsS http://127.0.0.1:19090/api/v1/status/config
```

Expect four ping send rates near 1/s and 13 successful scrape series (one exporter plus 12 service probes). `probe_success` may be zero during an actual outage despite `up=1`. Confirm replies and latency for normally reachable targets, all four ping-loss series after a full minute, five-minute panels after warm-up, and all 12 service targets in Grafana and CSV reports. Before deployment, all eight additional endpoints were checked from the workspace; repeat the checks through the GitOps-deployed exporter because routing and filtering may differ. New targets will initially have partial daily coverage. Verify rendered retention and rule health. Wait for completed UTC days before evaluating report coverage. Observe real incidents without deliberately interrupting the connection or changing live resources to test it.

References: [SmokePing Prober v0.12.0](https://github.com/SuperQ/smokeping_prober/tree/v0.12.0), [pro-bing socket modes](https://github.com/prometheus-community/pro-bing), [Blackbox configuration](https://github.com/prometheus/blackbox_exporter/blob/v0.29.0/CONFIGURATION.md).
