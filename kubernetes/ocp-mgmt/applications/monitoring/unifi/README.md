# UniFi Switch Monitoring

| Switch identity | SNMP target | Observed model / firmware |
|-----------------|-------------|---------------------------|
| `usw-enterprise-48-poe` | `192.168.1.10:161` | USW-Enterprise-48-PoE / 7.5.15.17146 |

## Collection and Credentials

Enable SNMPv3 in [UniFi Network](https://unifi.home.morey.tech:11443/) under **Settings → CyberSecure → Traffic Logging → SNMP**. UniFi provisions the configuration to the switch; Alloy polls the switch directly, not the controller. The device-level SNMP toggle is optional for Location and Contact metadata; the live probe succeeded while it was unchecked. See [Ubiquiti's SNMP instructions](https://help.ui.com/hc/en-us/articles/33502980942615-SNMP-Monitoring-in-UniFi-Network).

Bitwarden Login item `9773aa8d-9fcf-4a05-9152-b4de00156fda` supplies the SNMP username and password. [External Secrets](../unifi-credentials.yaml) renders `unifi-snmp-v1` using `bitwarden-login`. SNMPv3 uses `authPriv`, SHA authentication, and AES-128 privacy, with the same password for both as required by UniFi. Values are JSON-quoted within the YAML template and never stored in ConfigMaps or dashboard JSON.

Alloy watches the mounted auth file every minute and polls the switch every 60 seconds with a 30-second scrape deadline. Metrics use `job="unifi",instance="usw-enterprise-48-poe"` and are remote-written to infrastructure Prometheus. The Secret is a required Alloy volume: a reconciliation failure can block Alloy startup and affect other infrastructure collectors. Check ExternalSecret readiness during rollout. If restricting SNMP sources, permit the actual source used by Alloy on its eligible nodes (`ms-02`, `ms-04`); local probe success does not establish the deployed path.

The curated [SNMP module](snmp.yml) walks IF-MIB columns and reads SNMPv2-MIB identity/uptime. The switch returned 52 physical Ethernet interfaces (`0/1`–`0/52`, type 6), 26 aggregation interfaces (`3/1`–`3/26`, type 161), and one CPU interface (type 1). Unused interfaces remain visible. CPU-interface traffic is excluded from traffic graphs. An aggregation interface existing does not mean it is active.

Standard HOST-RESOURCES-MIB processor/memory tables, UCD-SNMP CPU/memory scalars, and POWER-ETHERNET-MIB PoE status/power objects returned no data on this firmware. These are probe limitations, not a claim that all vendor OIDs or the controller API lack these metrics. CPU, memory, temperature, and PoE panels remain deferred until a supported source is verified.

## Dashboard

Open [UniFi Switches](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/unifi-overview). The **Switch** dropdown isolates one device and is ready for additional targets. The Homelab dashboards menu links it to existing dashboards.

| Panels | Interpretation |
|--------|----------------|
| Collection, uptime, device/firmware | Scrape health, SNMP agent uptime in seconds, and reported identity; collection success is not overall device health |
| Port receive/transmit | Five-minute average bits/s from 64-bit counters on physical ports |
| LAG receive/transmit | Aggregation counters displayed separately; do not sum with member ports as unique traffic |
| Port link status/speed | Physical interface state and reported speed; speed is converted from Mbit/s to bits/s |
| Port utilization | Directional traffic divided by positive link speed; zero/missing speed gives gaps |
| Errors/discards | Five-minute packet rates, by direction and physical port |
| Interface descriptions | All interface names and configured aliases |

Graph legends use `ifAlias · ifName`, such as `ocp-home · 0/13`, with an interface-name fallback for empty/missing/stale aliases. Alias changes do not reset traffic-counter history. Every query requires successful collection and samples less than 180 seconds old. Missing telemetry is Unknown or gaps; actual idle ports remain zero. Traffic is measured from the switch's perspective: receive enters the port, transmit leaves it.

## Validation and Deployment

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-unifi-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-unifi-dashboard.py
snmp_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/unifi/snmp.yml --dry-run
alloy validate kubernetes/ocp-mgmt/applications/monitoring/config.alloy
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

Tests require PyYAML and `promtool` on PATH (or set `PROMTOOL`). They check generated JSON, layout, direction-specific counters, alias fallback, device isolation, counter resets, freshness, scrape failures, and zero link-speed handling.

Local validation passed 22 synthetic telemetry scenarios, module parsing, full Alloy validation, Kustomize rendering, and the non-persisting server dry run. A temporary local Alloy → Prometheus run authenticated to the switch and returned data for all 16 dashboard queries, including rates after two scrapes, 52 physical ports, and 26 aggregation interfaces. No cluster resources were changed.

After review, commit, human push, and Argo CD reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret unifi-snmp-v1
oc --context=logged-user -n monitoring rollout status deployment/alloy
oc --context=logged-user -n monitoring rollout status deployment/grafana
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-unifi.py
```

Allow two scrape intervals before checking traffic rates. The checker verifies the provisioned dashboard, source health, all 52 physical ports, aggregation interfaces, and each Grafana query path. Actual Alloy-to-switch connectivity, ExternalSecret reconciliation, and visual verification remain post-deployment checks.
