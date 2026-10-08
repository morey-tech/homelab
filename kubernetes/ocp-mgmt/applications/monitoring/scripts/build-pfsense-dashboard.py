#!/usr/bin/env python3
"""Build the pfSense dashboard from verified NET-SNMP metrics."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = {'type': 'prometheus', 'uid': 'infrastructure'}
PHYSICAL = '(igc|ix)[0-9]+'
LOGICAL = r'lagg[0-9]+(\.[0-9]+)?|pppoe[0-9]+|tun_wg[0-9]+|tailscale[0-9]+'
# Descriptions supplied by the operator; live nonempty ifAlias takes precedence.
INTERFACE_NAMES = {'ix2': 'WAN', 'lagg0': 'LAN', 'lagg0.3': 'LAB', 'lagg0.6': 'RH_LAB',
                   'lagg0.8': 'NETBOOT', 'lagg0.20': 'IOT',
                   'tun_wg0': 'WireGuard', 'tailscale0': 'Tailscale'}


def build():
    def selector(metric, extra=''):
        return f'{metric}{{job="pfsense",instance="pfsense"{"," + extra if extra else ""}}}'

    def fresh(metric, extra=''):
        s = selector(metric, extra)
        return f'({s} and (time() - timestamp({s}) < 180))'

    def observed(expr):
        return f'({expr}) and on(job, instance) ({fresh("up")} == 1)'

    def network_filter(pattern):
        return 'ifName=~' + json.dumps(pattern)

    def rate(metric, pattern, bits=False):
        extra = network_filter(pattern)
        return observed(f'({"8 * " if bits else ""}rate({selector(metric, extra)}[5m])) and {fresh(metric, extra)}')

    def named(expr):
        identity = 'job, instance, ifIndex, ifName'
        aliases = fresh('ifAlias', 'ifAlias!=""')
        names = f'label_join({aliases}, "interface", " · ", "ifAlias", "ifName")'
        fallback = f'label_replace(({expr}), "interface", "$1", "ifName", "(.*)")'
        for name, description in INTERFACE_NAMES.items():
            regex = json.dumps('(' + re.escape(name) + ')')
            fallback = f'label_replace({fallback}, "interface", {json.dumps(description + " · $1")}, "ifName", {regex})'
        return f'(({expr}) * on({identity}) group_left(interface) {names}) or on({identity}) {fallback}'

    panels = []

    def add(title, queries, x, y, w=12, h=7, unit='short', kind='timeseries', description=''):
        defaults = {'unit': unit, 'noValue': 'Unknown', 'decimals': 1, 'color': {'mode': 'palette-classic'}}
        p = {'id': len(panels) + 1, 'title': title, 'type': kind, 'datasource': DS,
             'description': description, 'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
             'fieldConfig': {'defaults': defaults, 'overrides': []},
             'targets': [{'refId': chr(65+i), 'datasource': DS, 'expr': expr, 'legendFormat': legend,
                          'editorMode': 'code', 'instant': kind != 'timeseries',
                          'range': kind == 'timeseries', 'interval': '1m'}
                         for i, (expr, legend) in enumerate(queries)]}
        if kind == 'timeseries':
            defaults.update({'min': 0, 'custom': {'drawStyle': 'line', 'lineWidth': 2,
                             'fillOpacity': 10, 'spanNulls': False, 'stacking': {'mode': 'none', 'group': 'A'}}})
            if unit == 'percent':
                defaults['max'] = 100
            p['options'] = {'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True},
                            'tooltip': {'mode': 'multi', 'sort': 'desc'}}
        elif kind == 'stat':
            p['options'] = {'reduceOptions': {'calcs': ['last'], 'fields': '', 'values': False},
                            'colorMode': 'value', 'graphMode': 'none', 'textMode': 'auto'}
        elif kind == 'table':
            p['targets'][0]['format'] = 'table'
            p['options'] = {'showHeader': True, 'cellHeight': 'sm'}
        panels.append(p)
        return p

    def mapping(p, values):
        mappings = [{'type': 'value', 'options': {
            str(code): {'text': text, 'color': color} for code, (text, color) in values.items()}}]
        if p['type'] == 'table':
            p['fieldConfig']['overrides'].append({'matcher': {'id': 'byName', 'options': 'Value'},
                                                'properties': [{'id': 'mappings', 'value': mappings}]})
        else:
            p['fieldConfig']['defaults']['mappings'] = mappings

    def table(title, expr, x, y, columns, w=12):
        p = add(title, [(expr, '')], x, y, w=w, kind='table')
        p['transformations'] = [{'id': 'filterFieldsByName', 'options': {'include': {'names': columns}}}]
        return p

    p = add('SNMP collection', [(f'{fresh("up")} or on() vector(-1)', '')], 0, 0, 6, 4, kind='stat',
            description='Collection success only, not firewall or gateway health. Samples older than 180 seconds are unknown.')
    mapping(p, {-1: ('Unknown', 'gray'), 0: ('Failed', 'red'), 1: ('Collecting', 'green')})
    add('SNMP uptime', [(observed(fresh('sysUpTime')), '')], 6, 0, 6, 4, unit='s', kind='stat',
        description='NET-SNMP agent uptime; restarts of the service reset this independently of firewall uptime.')
    add('CPU cores', [(observed(fresh('ssCpuNumCpus')), '')], 12, 0, 6, 4, kind='stat')
    add('Host', [(observed(fresh('sysName')), '{{sysName}}')], 18, 0, 6, 4, kind='stat')['options']['textMode'] = 'name'
    cpu = observed(fresh('hrProcessorLoad'))
    add('CPU usage', [(f'avg by (job, instance) ({cpu})', 'Overall'), (cpu, 'Processor {{hrDeviceIndex}}')],
        0, 4, 8, unit='percent', description='Approximately one-minute non-idle percentage per logical processor and their average.')
    memory = 'hrStorageDescr="Physical memory"'
    add('Memory usage', [(observed(f'100 * {fresh("hrStorageUsed", memory)} / ({fresh("hrStorageSize", memory)} > 0)'), 'Used')],
        8, 4, 8, unit='percent', description='Physical-memory allocation units used/total as reported by NET-SNMP. Does not identify ZFS ARC separately.')
    add('Load average', [(observed(fresh('laLoadFloat')), '{{laNames}}')], 16, 4, 8,
        description='System load over 1, 5, and 15 minutes; this is not a CPU percentage.')
    for title, pattern, y in [('Physical interface', PHYSICAL, 11), ('Logical interface', LOGICAL, 18)]:
        for direction, metric, x in [('receive', 'ifHCInOctets', 0), ('transmit', 'ifHCOutOctets', 12)]:
            add(title + ' ' + direction, [(named(rate(metric, pattern, bits=True)), '{{interface}}')], x, y, unit='bps',
                description='Five-minute average bits/s from the firewall perspective. Logical interfaces include LAG, VLAN, PPPoE, WireGuard, and Tailscale. '
                            'Counters overlap across layers; do not sum physical, LAG, VLAN, or tunnel traffic. Aliases fall back to interface names.')
    all_interfaces = PHYSICAL + '|' + LOGICAL
    for title, rx, tx, x in [('Interface errors', 'ifInErrors', 'ifOutErrors', 0), ('Interface discards', 'ifInDiscards', 'ifOutDiscards', 12)]:
        add(title, [(named(rate(rx, all_interfaces)), '{{interface}} RX'),
                    (named(rate(tx, all_interfaces)), '{{interface}} TX')], x, 25, unit='pps',
            description='Five-minute interface counter rates. These are not PF rule-block counts; historical totals are not current error rates.')
    p = table('Interface link status', named(observed(fresh('ifOperStatus', network_filter(all_interfaces)))),
              0, 32, ['interface', 'Value'])
    mapping(p, {1: ('Up', 'green'), 2: ('Down', 'yellow'), 3: ('Testing', 'yellow'), 4: ('Unknown', 'gray'),
                5: ('Dormant', 'yellow'), 6: ('Not present', 'gray'), 7: ('Lower layer down', 'yellow')})
    add('Physical link speed', [(named(observed(f'1000000 * {fresh("ifHighSpeed", network_filter(PHYSICAL))}')), '{{interface}}')],
        12, 32, unit='bps', description='Interface-reported speed in bits/s, not throughput. Inactive ports may retain a configured speed. '
                                                 'LAG/VLAN speeds are excluded because the current agent reports implausible values.')
    filesystems = 'hrStorageDescr=~"/.*",hrStorageDescr!~"/dev|/var/run"'
    add('Filesystem usage', [(observed(f'100 * {fresh("hrStorageUsed", filesystems)} / ({fresh("hrStorageSize", filesystems)} > 0)'), '{{hrStorageDescr}}')],
        0, 39, unit='percent', description='Per-filesystem used/total allocation units. ZFS datasets share capacity; do not sum them. Excludes /dev and /var/run.')
    add('Memory breakdown', [(observed(f'1024 * ({fresh("memTotalReal")} - {fresh("memAvailReal")})'), 'Used (total − available)'),
                             (observed(f'1024 * {fresh("memAvailReal")}'), 'Available (agent)'),
                             (observed(f'1024 * {fresh("memCached")}'), 'Cache (agent)'),
                             (observed(f'1024 * {fresh("memBuffer")}'), 'Buffers (agent)')],
        12, 39, unit='bytes', description='UCD memory counters converted from KiB to bytes. Agent accounting categories overlap and are not stacked. '
                                        'Cache is not an explicit ZFS ARC measurement.')
    table('System information', observed(fresh('sysDescr')), 0, 46, ['sysDescr'], w=24)
    return {'uid': 'pfsense-overview', 'title': 'pfSense Overview', 'schemaVersion': 39, 'version': 1,
            'editable': False, 'tags': ['homelab', 'infrastructure', 'pfsense'], 'timezone': 'browser',
            'refresh': '1m', 'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': []}, 'annotations': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/pfsense.json').write_text(json.dumps(build(), indent=2) + '\n')
