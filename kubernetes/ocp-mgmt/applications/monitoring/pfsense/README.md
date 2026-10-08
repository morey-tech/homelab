# pfSense Monitoring

The [pfSense Overview](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/pfsense-overview) uses the existing Infrastructure data source. Alloy polls NET-SNMP at **192.168.6.1:161** every 60 seconds with a 30-second scrape deadline, then remote-writes to infrastructure Prometheus with `job="pfsense",instance="pfsense"`. This is the explicitly bound SNMP address, not the `192.168.1.1` address resolved by `pfsense.home.morey.tech`.

Verified platform: **pfSense Plus 26.03-RELEASE, amd64, FreeBSD 16.0-CURRENT**, with four logical processors. The dedicated module walks selected IF-MIB, HOST-RESOURCES-MIB, and UCD-SNMP-MIB columns, with at most ten repetitions, one retry, and a three-second request timeout. It does not enumerate firewall rules, connections, or installed software.

## Credentials and Access

NET-SNMP uses a read-only SNMPv3 user with `authPriv`, SHA authentication, and AES privacy. The built-in SNMP service must not occupy the same address/port. Keep the SNMP listener on the internal interface; restrict UDP 161 to the actual monitoring source addresses seen by pfSense. Alloy runs on eligible nodes `ms-02` or `ms-04`.

Bitwarden Login item `913a8afa-4bfc-4dd5-91b0-b4dd0018d51d` supplies:

| Field | Purpose |
|-------|---------|
| Username | SNMPv3 security name |
| Password | Authentication password |
| Hidden custom field `priv_password` | Encryption password |

[External Secrets](../pfsense-credentials.yaml) reads `bitwarden-login` and `bitwarden-fields` to render `pfsense-snmp-v1`. Fields are JSON-quoted in the YAML template. Alloy reads the mounted auth document as secret and reloads projected Secret updates through a one-minute file poll. External Secrets refreshes hourly after the Bitwarden cache synchronizes; rotate pfSense and Bitwarden credentials together.

The Secret is a required Alloy volume. A missing Secret blocks Alloy startup, including existing QNAP and MikroTik collection. Verify Secret synchronization during rollout. Grafana and the cluster Thanos data sources are independent of Alloy.

## Dashboard Semantics

| Panels | Interpretation |
|--------|----------------|
| SNMP collection, uptime, CPU cores, host | Collector status and agent identity; SNMP service uptime is not firewall uptime |
| CPU usage | Per-core approximately one-minute utilization and the mean across cores |
| Memory usage | Physical-memory used/total allocation units reported by NET-SNMP |
| Load average | One-, five-, and fifteen-minute system load, not a percentage |
| Physical interface receive/transmit | Five-minute bits/s for `igc*` and `ix*` ports, including idle ports |
| Logical interface receive/transmit | Separate LAG, VLAN, PPPoE, WireGuard, and Tailscale rates |
| Interface errors/discards | Five-minute packet rates; these are not PF rule-block counts |
| Interface link status | Operational status for the monitored physical and logical interfaces |
| Physical link speed | Reported physical-port speed; inactive ports may retain a configured speed |
| Filesystem usage | Used/total per filesystem, excluding `/dev` and `/var/run`; datasets share capacity |
| Memory breakdown | Agent-reported used (total minus available), available, cache, and buffers in bytes |
| System information | Agent-reported pfSense/FreeBSD version and architecture |

Physical, LAG, VLAN, and tunnel counters overlap: **do not sum them into a unique traffic total**. Receive/transmit are from the firewall's perspective. The current agent reports implausible LAG/VLAN link speeds, so speed graphs use physical interfaces only. Memory categories overlap and are not stacked; cache is not an explicit ZFS ARC measurement. Filesystem capacities must not be summed across ZFS datasets.

All values require a successful scrape and samples less than 180 seconds old. Missing data stays unknown or appears as graph gaps; idle counters remain valid zeros. Rate queries require at least two samples and handle counter resets. Collection success does not establish firewall, WAN gateway, or VPN health.

NET-SNMP returned no samples for the probed BEGEMOT PF status, state-count, or state-limit OIDs. PF states/rules/queues, gateway latency/loss, VPN health, and explicit ARC accounting are not included in this dashboard. Adding them requires another verified metric source; the built-in daemon's PF module is not assumed available through NET-SNMP.

## Interface Names

The operator confirmed these assignments. They supply graph and link-table labels while SNMP `ifAlias` is empty:

| Interface | Display label |
|-----------|---------------|
| `ix2` | WAN |
| `lagg0` | LAN |
| `lagg0.3` | LAB |
| `lagg0.6` | RH_LAB |
| `lagg0.8` | NETBOOT |
| `lagg0.20` | IOT |
| `tun_wg0` | WireGuard |
| `tailscale0` | Tailscale |

Legends retain the interface name, for example `WAN · ix2`. A fresh nonempty `ifAlias` takes precedence; unknown interfaces keep their raw names. Update `INTERFACE_NAMES`, `PHYSICAL`, and `LOGICAL` in [the generator](../scripts/build-pfsense-dashboard.py) when assignments or interface naming change. No pfSense interface settings are changed by this integration.

## Validation and Deployment

Regenerate and validate locally:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-pfsense-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-pfsense-dashboard.py
snmp_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/pfsense/snmp.yml --dry-run
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

The test script requires PyYAML and `promtool` on PATH (or set `PROMTOOL`). It checks generated JSON, missing/stale/failed telemetry, bytes-to-bits and KiB-to-bytes conversion, counter resets, aliases and configured labels, separation of physical/logical interfaces, CPU averaging, and memory/filesystem denominators.

The pfSense dashboard has its own generated ConfigMap, projected alongside the existing dashboards into Grafana's provisioned directory. Keeping it separate avoids the 256 KiB apply-annotation limit on the combined dashboard ConfigMap. Kustomize rewrites both references to their content hashes, so GitOps changes trigger the Grafana rollout.

Pre-deployment validation passed 29 synthetic telemetry scenarios, SNMP module parsing, Alloy configuration validation, Kustomize rendering, and a non-persisting server-side dry run. A temporary local Alloy → Prometheus pipeline polled all five devices with credentials held in memory; all 126 dashboard queries returned data after two scrapes (24 pfSense, 46 MikroTik, and 56 QNAP). This validates queries against live counters without changing cluster resources.

After review, commit, human push, and Argo CD reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret pfsense-snmp-v1
oc --context=logged-user -n monitoring rollout status deployment/alloy
oc --context=logged-user -n monitoring rollout status deployment/grafana
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-pfsense.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-mikrotik.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-qnap.py
```

Allow two scrape intervals before checking traffic rates. The read-only pfSense checker uses the Grafana admin Secret in memory, checks the provisioned dashboard and data source, and executes every query through both the datasource proxy and Grafana panel plugin. Cluster-to-firewall access and provisioned dashboard rendering remain post-deployment checks; do not apply uncommitted manifests for validation.

References: [pfSense packages](https://docs.netgate.com/pfsense/en/latest/packages/list.html), [built-in SNMP modules](https://docs.netgate.com/pfsense/en/latest/services/snmp.html), [snmp_exporter v0.29.0 standard modules](https://github.com/prometheus/snmp_exporter/blob/v0.29.0/snmp.yml).
