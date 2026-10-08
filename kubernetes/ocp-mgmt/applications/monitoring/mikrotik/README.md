# MikroTik RouterOS Monitoring

| Switch | SNMP target | Model | Observed RouterOS |
|--------|-------------|-------|-------------------|
| `crs317-a` | `192.168.1.15:161` | CRS317-1G-16S+ | 7.24.1 stable |
| `crs317-b` | `192.168.1.16:161` | CRS317-1G-16S+ | 7.24.1 stable |

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

## Metric Collection and Validation

The curated [snmp.yml](snmp.yml) collects selected system, interface, host-resource, and MikroTik health counters. RouterOS interface names and types identify ports and bonds; indexes differ between these switches. Both switches returned authenticated SNMP responses on RouterOS 7.24.1 in about 0.6–0.7 seconds without retries.

```bash
snmp_exporter --config.file=kubernetes/ocp-mgmt/applications/monitoring/mikrotik/snmp.yml --dry-run
oc kustomize kubernetes/ocp-mgmt/applications/monitoring > /tmp/monitoring.yaml
oc --context=logged-user apply --dry-run=server -f /tmp/monitoring.yaml
```

Deploy through GitOps after review, commit, and push. Check `mikrotik-snmp-v1` ExternalSecret reconciliation and `up{job="mikrotik"}` for both switch instances after rollout. The Grafana dashboard is added in the next commit.
