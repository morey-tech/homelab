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

## Validation and Deployment

```bash
snmp_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/unifi/snmp.yml --dry-run
alloy validate kubernetes/ocp-mgmt/applications/monitoring/config.alloy
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

The authenticated read-only probe verified 52 physical ports and 26 aggregation interfaces. Module parsing, full Alloy validation, Kustomize rendering, and the non-persisting server dry run passed. A temporary local Alloy → Prometheus run collected counters and rates after two scrapes. No cluster resources were changed.

After review, commit, human push, and Argo CD reconciliation:

```bash
oc --context=logged-user -n monitoring get externalsecret unifi-snmp-v1
oc --context=logged-user -n monitoring rollout status deployment/alloy
```

Actual Alloy-to-switch connectivity and ExternalSecret reconciliation remain post-deployment checks.
