# QNAP Monitoring

Target: `qnap-01.rh-lab.morey.tech` (`192.168.6.20`), running QuTS hero `h5.2.9.3499 Build 20260514`.

Alloy polls the NAS every 60 seconds and forwards samples to the internal Prometheus remote-write receiver. Grafana queries them through the Infrastructure data source. Changes deploy through the management monitoring Application after review, commit, and push.

## SNMPv3 credential setup

In **Control Panel → Network & File Services → SNMP**, configure SNMPv3 with authentication and privacy (`authPriv`). This NAS offers HMAC-SHA or HMAC-MD5 authentication and CBC-DES privacy. Use **HMAC-SHA + CBC-DES**, configured as `SHA` and `DES` in the exporter. Both **Use Authentication** and **Use Privacy** must be enabled. Use a dedicated SNMP identity and read-only access where the device offers that setting. Collection polls UDP port 161; traps are not required.

Bitwarden **Login** item **QNAP monitoring SNMPv3** (`29df3066-0d03-464d-bf35-b4dc017a372e`) contains:

| Field | Value |
|-------|-------|
| Username | SNMPv3 username, not a QNAP administrator login |
| Password | SNMPv3 authentication password |
| Hidden custom field `priv_password` | SNMPv3 privacy password |

External Secrets uses `bitwarden-login` for the username/password and `bitwarden-fields` for the privacy password. Never put credential values in Git, dashboard JSON, or shell arguments.

## Metric source

[NAS.mib](NAS.mib) is a copy of the MIB supplied from this NAS, with trailing whitespace normalized. The curated [snmp.yml](snmp.yml) module uses `qnap.qutshero` (`1.3.6.1.4.1.55062.2`), not the older QNAP enterprise tree. It requests selected scalars and table columns rather than walking every application and service.

| Metrics | Interpretation |
|---------|----------------|
| `storagepoolCapacity`, `storagepoolFreeSize` | Pool total/free bytes; used = total − free |
| `storagepoolStatus` | QuTS hero state codes from the MIB's description; Ready = 0 |
| `sharedFolderCapacity`, `sharedFolderFreeSize` | Logical shared-folder total/free bytes; distinct from pool accounting |
| `sharedFolderStatus`, `raidStatus`, `diskStatus` | Device-reported text, retained as labels and shown in tables |
| `systemCPU_Usage` | CPU usage percentage; live sample returned 18 |
| `systemTotalMem`, `systemAvailableMem` | MIB does not specify units; dashboard uses their ratio only |
| `systemUsedMemory`, `systemFreeMem`, `systemCacheMemory`, `systemBufferMemory` | NAS-reported used, free, cache, and buffer counters; shown as percentages of total memory |
| `sysUptime` | TimeTicks converted from hundredths of a second to seconds |
| Temperatures, fan speed, power status | Hardware telemetry; live availability must be checked |

Capacity and memory objects use the MIB's `Counter64` encoding but represent **gauges**, not cumulative counters. Do not apply `rate()` to these values. Pool IDs, disk IDs, RAID names, and shared-folder names are looked up from their table rows.

The [QNAP dashboard](../dashboards/qnap.json) expects an `infrastructure` Prometheus data source and series labeled `job="qnap", instance="qnap-01"`. It separates pool capacity from logical share usage, guards panels with a successful SNMP scrape, and treats samples older than 180 seconds as missing. The collection panel describes collection success, not overall NAS health. Text health values are shown verbatim until live response semantics are verified.

Expected shares from the monitoring plan are `storage-media` and `storage-mass` on pool 1, and `storage-nvme` on pool 2. The MIB does not expose a share-to-pool association in this table: validate these mappings in QNAP before adding mapping labels. Do not infer pool consumption by summing shares; snapshots, reservations, compression, and thin provisioning can affect the two accounts differently.

## Memory Breakdown

The Homelab Overview memory card and the detailed QNAP dashboard's **Memory breakdown** graph show five separate lines: **Used (NAS)**, **Available**, **Free**, **Cache (NAS)**, and **Buffers**. Each counter is divided by total memory and displayed with two decimal places, so small buffer/cache values remain visible. These counters overlap; the graphs are deliberately unstacked and their values must not be summed. Missing counters remain missing rather than being replaced with zero.

The existing **Memory in use** summary remains `100 × (1 − available / total)`. In the live validation sample, the NAS-reported used counter equaled total minus available (about 30%), while free memory was about 11%, cache 1.23%, and buffers 0.06%. Available memory is not the same as free memory.

The supplied MIB has **no explicit ZFS ARC counter**. [QNAP documents ARC separately from used memory in Resource Monitor](https://www.qnap.com/en/how-to/faq/article/why-do-i-receive-an-insufficient-memory-error-when-there-appears-to-be-enough-ram-available), but the MIB does not define its generic cache counter as ARC. This integration neither renames cache as ARC nor estimates ARC from the difference between other counters. Direct ARC collection is deferred to a later NAS metrics or SSH integration.

The four additional counters begin accumulating history after the collector change deploys through GitOps; prior history is not backfilled.

## Local validation

Regenerate the dashboard:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-qnap-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-overview-dashboard.py
```

With the upstream SNMP exporter available:

```bash
snmp_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/qnap/snmp.yml --dry-run
```

Run the dashboard query checks using `promtool` on PATH:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-qnap-dashboard.py
```

## Read-only Validation

A direct SNMPv3 scrape using the Bitwarden credential returned a TS-873A on the expected firmware, two Ready pools, six Ready shares (including all three expected shares), two Ready RAID groups, and nine Good disks. CPU, memory, fan, temperature, power, and uptime metrics were also present. The full scrape took about 31 seconds with 125 packets and no retries.

The deployed Alloy and Prometheus versions also passed a temporary local pipeline test: Alloy collected the live NAS, remote-wrote to local Prometheus, and all 24 queries across 20 panels returned data with the expected labels, including the five memory breakdown series. No cluster resources were changed for this validation. Cluster rollout, ExternalSecret reconciliation, and Grafana's panel-plugin queries remain post-deployment checks.

GETBULK requests with `max_repetitions: 10` timed out; `max_repetitions: 1` completed successfully. The expanded memory scrape exceeded the previous 45-second deadline in local Alloy validation. Keep the 55-second scrape timeout below the 60-second interval and monitor scrape duration after deployment. Pool 1 reported about 57.86 TB total and 9.73 TB free; pool 2 about 936.30 GB total and 736.02 GB free (decimal units). These are SNMP observations, not a comparison against the NAS UI. Compare the initial dashboard with QNAP's Storage & Snapshots page.

## Credential Rotation

Update the NAS SNMP passwords and the matching Bitwarden fields together. The Bitwarden service synchronizes its cache periodically, and External Secrets refreshes hourly. The projected `qnap-snmp-v1` Secret is mounted as a directory without `subPath`; Alloy polls its file every minute and reloads credentials without a pod restart. A temporary scrape failure during rotation is expected. Alloy's UI treats the whole authentication document as a secret.

## After GitOps Deployment

```bash
oc --context=logged-user -n monitoring get externalsecret qnap-snmp-v1
oc --context=logged-user -n monitoring rollout status deployment/alloy
oc --context=logged-user -n monitoring rollout status deployment/prometheus
oc --context=logged-user -n monitoring rollout status deployment/grafana
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-qnap.py
```

The ExternalSecret should be `SecretSynced`. A missing Secret blocks Alloy startup without blocking Grafana. In Grafana Explore, select **Infrastructure** and query `up{job="qnap",instance="qnap-01"}`; expect `1`. Confirm both pools and the expected shared folders appear, compare the displayed capacities with QNAP, and inspect the device-reported status strings. A healthy Alloy HTTP endpoint alone does not prove successful SNMP collection.

The dashboard's collection status means the exporter completed its scrape, not that every expected disk, share, or pool exists or is healthy. Inspect those panels as well. Actual device inventory and Grafana queries must be checked after deployment; no local manifests are applied directly.
