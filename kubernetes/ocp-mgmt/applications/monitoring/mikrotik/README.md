# MikroTik RouterOS Monitoring

| Switch | SNMP target | Model | Observed RouterOS |
|--------|-------------|-------|-------------------|
| `crs317-a` | `192.168.1.15:161` | CRS317-1G-16S+ | 7.24.1 stable |
| `crs317-b` | `192.168.1.16:161` | CRS317-1G-16S+ | 7.24.1 stable |

Open [MikroTik Switches](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/mikrotik-overview) and use the **Switch** dropdown. [Open crs317-b directly](https://grafana.apps.ocp-mgmt.rh-lab.morey.tech/d/mikrotik-overview?var-switch=crs317-b). Selection applies to every panel, including collection health. The Homelab dashboards menu links it with the existing dashboards.

Alloy polls both switches every 60 seconds with a 30-second deadline and remote-writes to infrastructure Prometheus. Each target has `job="mikrotik"` and a distinct `instance` (`crs317-a` or `crs317-b`). The exporter sets its own initial instance label, so discovery relabeling assigns the switch identity afterwards. The [legacy Ansible SwOS configuration](../../../../../ansible/files/monitoring/config.alloy) is independent of this RouterOS integration.

## Credentials and RouterOS Setup

Both switches use SNMPv3 `authPriv`, SHA1 authentication, and AES encryption. RouterOS names the security setting `private`; snmp_exporter uses `SHA` and `AES`. Configure **IP → SNMP → Communities** with read access enabled and write access disabled, then enable SNMP. Traps are not required. See the [RouterOS SNMP manual](https://manual.mikrotik.com/docs/diagnostics-monitoring-and-troubleshooting/snmp/).

Bitwarden Login item `b174080a-c3ec-4e7b-9afa-b4dd000e3bbd` supplies:

| Field | Purpose |
|-------|---------|
| Username | RouterOS SNMP community/security name |
| Password | Authentication password |
| Hidden custom field `priv_password` | Encryption password |

[External Secrets](../mikrotik-credentials.yaml) uses `bitwarden-login` and `bitwarden-fields` to render `mikrotik-snmp-v1`. Credential strings are JSON-quoted within the YAML template and never included in ConfigMaps or dashboard JSON. Alloy marks the mounted auth document as secret and polls it for changes every minute. Rotate the switch settings and Bitwarden fields together; External Secrets refreshes hourly after the Bitwarden cache synchronizes.

The Secret is a required Alloy volume. If provisioning fails, Alloy cannot start and both switch and NAS collection are affected; Grafana and its OpenShift data sources remain independent. Verify ExternalSecret reconciliation during rollout. If switch SNMP source-address restrictions are enabled, allow the actual source seen from Alloy on its eligible nodes (`ms-02` and `ms-04`), not merely the local validation host.

## Metrics and Dashboard Semantics

The curated [snmp.yml](snmp.yml) collects selected system, IF-MIB, HOST-RESOURCES-MIB, and MikroTik health objects. It avoids broad RouterOS routing/wireless walks. MikroTik vendor OIDs and health unit codes are based on the [snmp_exporter v0.29.0 module](https://github.com/prometheus/snmp_exporter/blob/v0.29.0/snmp.yml); standard memory/CPU semantics follow [HOST-RESOURCES-MIB](https://www.net-snmp.org/docs/mibs/HOST-RESOURCES-MIB.txt).

| Panels | Interpretation |
|--------|----------------|
| SNMP collection | Successful collection, not overall switch health; missing/stale collection is Unknown |
| SNMP uptime, RouterOS, model | Agent uptime converted from TimeTicks to seconds; device-reported identity |
| CPU usage | Per-processor approximately one-minute non-idle percentage |
| Memory usage | Used/total allocation units for `main memory`; excludes `system disk` |
| Port receive/transmit | Five-minute average bits/s from 64-bit counters, filtered by `ifType=6` |
| Bond receive/transmit | Separate rates for `ifType=161`; no combined total across ports, bonds, or switches |
| Port link status/speed | All 17 physical ports, including missing SFPs; `ifHighSpeed` converted from Mbit/s to bits/s |
| Port utilization | Receive and transmit rates divided separately by positive link speed; unknown/zero speed gives gaps |
| Port errors/discards | Five-minute packet rates, separated by direction and interface |
| Temperature/fan speed | Generic RouterOS gauges selected by unit code: 1=Celsius, 2=RPM |
| Power supplies | Legacy PSU-OK booleans: 1=OK, 0=Not OK; an unpowered supply can report Not OK |
| Interface descriptions | RouterOS interface names and comments, including named MLAG bonds |

Both switches reported 17 Ethernet ports, nine bonds, a bridge, and loopback. Their interface indexes differ. Queries identify ports by type and show names rather than assuming identical indexes across switches. Port and bond counters overlap; summing them or both MLAG peers does not measure unique traffic. Physical-port graphs cover hardware interface traffic without using CPU load as a proxy for switching throughput. The dashboard does not infer MLAG health from link status.

Queries require a successful scrape and samples less than 180 seconds old. Missing counters stay missing; idle interfaces remain valid zeros. Rate queries require at least two successful scrapes and handle counter resets. History begins after GitOps deployment.

## Validation and Deployment

Regenerate and validate locally:

```bash
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/build-mikrotik-dashboard.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/test-mikrotik-dashboard.py
snmp_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/mikrotik/snmp.yml --dry-run
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

The test script needs Python PyYAML and `promtool` on PATH (or set `PROMTOOL`). Read-only SNMP probes authenticated to both switches using the Bitwarden item. Each scrape completed in about 0.6–0.7 seconds with no retries. Both exposed two processors, 1 GiB of memory, CPU/SFP temperature, and two fans. Both reported primary PSU OK and backup PSU not OK; compare with the actual connected power supplies rather than assuming a hardware fault.

The complete edited Alloy configuration also passed a temporary local Alloy → Prometheus test against both switches and both NAS devices. All 102 dashboard queries returned data with isolated device identities (23 per switch and 28 per NAS), including traffic rates after two scrapes. Local validation passed 17 RouterOS telemetry scenarios, the existing 32 QNAP scenarios, SNMP module parsing, Kustomize rendering, and a non-persisting server-side dry run.

After review, commit, human push, and Argo CD reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret mikrotik-snmp-v1
oc --context=logged-user -n monitoring rollout status deployment/alloy
oc --context=logged-user -n monitoring rollout status deployment/grafana
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-mikrotik.py
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-qnap.py
```

Allow two scrape intervals before checking network rates. The MikroTik checker verifies both devices, their expected physical ports, bond count, datasource proxy queries, and Grafana plugin queries. Use `--switch crs317-b` to check just one device. Cluster-to-switch access and the provisioned Grafana dashboard remain post-deployment checks; do not apply uncommitted resources to test them.
