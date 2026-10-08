# QNAP Monitoring

| NAS | SNMP target | Model | QuTS hero |
|-----|-------------|-------|-----------|
| `qnap-01` | `192.168.6.20` (`qnap-01.rh-lab.morey.tech`) | TS-873A | `h5.2.9.3499 Build 20260514` |
| `qnap-02` | `qnap-02.taile3c3a8.ts.net` | TS-873A | `h5.2.10.3577 Build 20260731` |

Alloy polls each NAS every 60 seconds and forwards samples to the internal Prometheus remote-write receiver, preserving `job="qnap"` with distinct `instance` labels. Grafana queries them through the Infrastructure data source. Changes deploy through the management monitoring Application after review, commit, and push.

Use the **NAS** dropdown on [QNAP Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/qnap-overview) to select one device. It defaults to `qnap-01`; [open qnap-02 directly](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/qnap-overview?var-nas=qnap-02). Every panel, including collection health, follows this selection. There is no combined selection that could mix capacity or health between devices. Homelab Overview remains pinned to `qnap-01`.

The existing Alloy pod resolved and successfully scraped qnap-02 through the current network route to its tailnet address. No new Tailscale proxy is required. This relies on the existing DNS, routing, and tailnet access remaining available from Alloy's nodes.

## SNMPv3 credential setup

In **Control Panel → Network & File Services → SNMP**, configure SNMPv3 with authentication and privacy (`authPriv`). This NAS offers HMAC-SHA or HMAC-MD5 authentication and CBC-DES privacy. Use **HMAC-SHA + CBC-DES**, configured as `SHA` and `DES` in the exporter. Both **Use Authentication** and **Use Privacy** must be enabled. Use a dedicated SNMP identity and read-only access where the device offers that setting. Collection polls UDP port 161; traps are not required.

Both NAS devices use the same SNMPv3 credentials and SHA/DES settings. Bitwarden **Login** item **QNAP monitoring SNMPv3** (`29df3066-0d03-464d-bf35-b4dc017a372e`) contains:

| Field | Value |
|-------|-------|
| Username | SNMPv3 username, not a QNAP administrator login |
| Password | SNMPv3 authentication password |
| Hidden custom field `priv_password` | SNMPv3 privacy password |

External Secrets uses `bitwarden-login` for the username/password and `bitwarden-fields` for the privacy password. Never put credential values in Git, dashboard JSON, or shell arguments.

## Metric source

[NAS.mib](NAS.mib) is a copy of the MIB supplied from qnap-01, with trailing whitespace normalized. The curated [snmp.yml](snmp.yml) module uses `qnap.qutshero` (`1.3.6.1.4.1.55062.2`), plus standard HOST-RESOURCES-MIB processor load and IF-MIB network counters. It requests selected scalars and table columns rather than walking every application and service.

| Metrics | Interpretation |
|---------|----------------|
| `storagepoolCapacity`, `storagepoolFreeSize` | Pool total/free bytes; used = total − free |
| `storagepoolStatus` | QuTS hero state codes from the MIB's description; Ready = 0 |
| `sharedFolderCapacity`, `sharedFolderFreeSize` | Logical shared-folder total/free bytes; distinct from pool accounting |
| `sharedFolderStatus`, `raidStatus`, `diskStatus` | Device-reported text, retained as labels and shown in tables |
| `systemCPU_Usage` | CPU usage percentage; live sample returned 18 |
| `hrProcessorLoad` | Per-logical-processor non-idle percentage, approximately a one-minute average; labeled by SNMP `hrDeviceIndex` |
| `ifHCInOctets`, `ifHCOutOctets` | 64-bit received/transmitted byte counters, labeled by `ifIndex` and `ifName`; dashboard converts rates to bits per second |
| `systemTotalMem`, `systemAvailableMem` | MIB does not specify units; dashboard uses their ratio only |
| `systemUsedMemory`, `systemFreeMem`, `systemCacheMemory`, `systemBufferMemory` | NAS-reported used, free, cache, and buffer counters; shown as percentages of total memory |
| `sysUptime` | TimeTicks converted from hundredths of a second to seconds |
| Temperatures, fan speed, power status | Hardware telemetry; live availability must be checked |

Capacity and memory objects use the MIB's `Counter64` encoding but represent **gauges**, not cumulative counters. Do not apply `rate()` to these values. Pool IDs, disk IDs, RAID names, and shared-folder names are looked up from their table rows.

The [QNAP dashboard](../dashboards/qnap.json) expects an `infrastructure` Prometheus data source and series labeled `job="qnap"`, with `instance` matching the selected NAS. It separates pool capacity from logical share usage, guards panels with a successful SNMP scrape, and treats samples older than 180 seconds as missing. The collection panel describes collection success, not overall NAS health. Text health values are shown verbatim until live response semantics are verified.

For qnap-01, expected shares from the monitoring plan are `storage-media` and `storage-mass` on pool 1, and `storage-nvme` on pool 2. `qnap-02` returned one pool, five shares (`Public`, `storage-mass`, `storage-media`, `time-machine`, and `Container`), one RAID group, and eight disks. The MIB does not expose a share-to-pool association in this table: validate these mappings in QNAP before adding mapping labels. Do not infer pool consumption by summing shares; snapshots, reservations, compression, and thin provisioning can affect the two accounts differently.

## CPU Breakdown

The detailed QNAP dashboard's **CPU breakdown** graph shows **Overall (NAS)** plus one line per logical processor. The Homelab Overview CPU card initially shows only **Overall (NAS)**, using Grafana's saved legend selection; Ctrl/Cmd-click a processor in the legend to add its line. A read-only probe returned eight processors, with SNMP indexes `196608` through `196615`. These are SNMP device indexes, not physical-core counts or OS CPU numbers. Each line is independently scaled from 0–100%; the lines are not stacked or summed.

The [HOST-RESOURCES-MIB](https://www.net-snmp.org/docs/mibs/HOST-RESOURCES-MIB.txt) defines `hrProcessorLoad` (`1.3.6.1.2.1.25.3.3.1.2`) as a processor's non-idle percentage averaged over approximately one minute. This is a gauge, so no `rate()` is applied. The QNAP overall value may use a different sampling window and need not equal the mean of the processor lines at a given time. All series require successful, fresh SNMP collection; an idle processor remains a valid zero, while missing or stale processors show gaps.

The NAS did not return the probed UCD-SNMP CPU-time counters (user, nice, system, idle, I/O wait, kernel, interrupts, soft IRQ, or steal), nor the standard 1/5/15-minute load-average column, with the current SNMP identity. Those metrics are not added as empty panels or inferred from overall utilization. A NAS exporter or SSH-based collector would be needed to investigate these further, alongside the deferred ARC integration.

The new processor series begin accumulating history after deployment; earlier history is not backfilled.

## Memory Breakdown

The Homelab Overview memory card and the detailed QNAP dashboard's **Memory breakdown** graph show five separate lines: **Used (NAS)**, **Available**, **Free**, **Cache (NAS)**, and **Buffers**. Each counter is divided by total memory and displayed with two decimal places, so small buffer/cache values remain visible. These counters overlap; the graphs are deliberately unstacked and their values must not be summed. Missing counters remain missing rather than being replaced with zero.

The existing **Memory in use** summary remains `100 × (1 − available / total)`. In the live validation sample, the NAS-reported used counter equaled total minus available (about 30%), while free memory was about 11%, cache 1.23%, and buffers 0.06%. Available memory is not the same as free memory.

The supplied MIB has **no explicit ZFS ARC counter**. [QNAP documents ARC separately from used memory in Resource Monitor](https://www.qnap.com/en/how-to/faq/article/why-do-i-receive-an-insufficient-memory-error-when-there-appears-to-be-enough-ram-available), but the MIB does not define its generic cache counter as ARC. This integration neither renames cache as ARC nor estimates ARC from the difference between other counters. Direct ARC collection is deferred to a later NAS metrics or SSH integration.

The four additional counters begin accumulating history after the collector change deploys through GitOps; prior history is not backfilled.

## Network Usage

The QNAP-specific dashboard includes **Network receive** and **Network transmit** graphs. Each uses `8 × rate(counter[5m])` to show a five-minute average in bits per second, automatically scaled to Kbit/s, Mbit/s, or Gbit/s. The [IF-MIB](https://www.net-snmp.org/docs/mibs/IF-MIB.txt) supplies 64-bit octet counters and interface names; these are cumulative counters, unlike the memory gauges.

The graphs show Ethernet ports, bonds, and their VLAN interfaces matching `(eth|bond)[0-9]+([.][0-9]+)?`. The qnap-01 probe returned `eth0`–`eth3`, `bond0`–`bond3`, `bond0.3`, and `bond0.6`. Each line includes its interface name and SNMP index. Loopback and virtual bridges are excluded from these graphs, although their counters are collected. Do not sum interfaces: the same traffic can pass through a physical port, bond, and VLAN. Lines are not stacked.

Rates require at least two successful scrapes after deployment; no earlier network history is backfilled. Counter resets are handled by `rate()`. Missing or stale counters and failed collection show gaps rather than a false zero. The shared Homelab Overview shows receive and transmit rates for qnap-01 `bond0` together in the third QNAP card, alongside CPU and memory. Pool and shared-folder details remain on the QNAP-specific dashboard.

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

The deployed Alloy and Prometheus versions also passed a temporary local pipeline test with both NAS targets: all 28 queries across 23 panels returned live data for each NAS (56 checks), with the selected `instance` on every result. Both returned five memory breakdown series and eight logical-processor CPU series. After two successful scrapes, network rates covered ten interfaces on qnap-01 and four on qnap-02. The 32 PromQL scenarios also check that NAS selection isolates values and scrape health. No cluster resources were changed for this validation. Cluster rollout, ExternalSecret reconciliation, and Grafana's panel-plugin queries remain post-deployment checks.

GETBULK requests with `max_repetitions: 10` timed out; `max_repetitions: 1` completed successfully. The expanded memory scrape exceeded the previous 45-second deadline in local Alloy validation. Keep the 55-second scrape timeout below the 60-second interval and monitor scrape duration after deployment. Pool 1 reported about 57.86 TB total and 9.73 TB free; pool 2 about 936.30 GB total and 736.02 GB free (decimal units). These are SNMP observations, not a comparison against the NAS UI. Compare the initial dashboard with QNAP's Storage & Snapshots page.

## Credential Rotation

Update both NAS devices' SNMP passwords and the matching Bitwarden fields together. The Bitwarden service synchronizes its cache periodically, and External Secrets refreshes hourly. The projected `qnap-snmp-v1` Secret is mounted as a directory without `subPath`; Alloy polls its file every minute and reloads credentials without a pod restart. A temporary scrape failure during rotation is expected. Alloy's UI treats the whole authentication document as a secret.

## After GitOps Deployment

```bash
oc --context=logged-user -n monitoring get externalsecret qnap-snmp-v1
oc --context=logged-user -n monitoring rollout status deployment/alloy
oc --context=logged-user -n monitoring rollout status deployment/prometheus
oc --context=logged-user -n monitoring rollout status deployment/grafana
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-qnap.py
```

The ExternalSecret should be `SecretSynced`. A missing Secret blocks Alloy startup without blocking Grafana. In Grafana Explore, select **Infrastructure** and query `up{job="qnap"}`; expect two series with distinct `instance` labels, both `1`. The checker verifies both devices by default; pass `--nas qnap-02` to check only the second NAS. Confirm the expected pools and shares for each NAS, compare the displayed capacities with QNAP, and inspect the device-reported status strings. A healthy Alloy HTTP endpoint alone does not prove successful SNMP collection.

The dashboard's collection status means the exporter completed its scrape, not that every expected disk, share, or pool exists or is healthy. Inspect those panels as well. Actual device inventory and Grafana queries must be checked after deployment; no local manifests are applied directly.
