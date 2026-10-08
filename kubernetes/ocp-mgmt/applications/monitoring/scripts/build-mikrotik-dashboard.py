#!/usr/bin/env python3
"""Build the RouterOS switch dashboard from verified SNMP counters."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = {'type': 'prometheus', 'uid': 'infrastructure'}
SWITCHES = ['crs317-a', 'crs317-b']


def build(switch='$switch'):
    labels = f'job="mikrotik",instance={json.dumps(switch)}'

    def selector(metric, extra=''):
        return f'{metric}{{{labels}{"," + extra if extra else ""}}}'

    def fresh(metric, extra=''):
        s = selector(metric, extra)
        return f'({s} and (time() - timestamp({s}) < 180))'

    def observed(expr):
        return f'({expr}) and on(job, instance) ({fresh("up")} == 1)'

    def interfaces(expr, kind=6):
        return f'({expr}) and on(job, instance, ifIndex) ({fresh("ifType")} == {kind})'

    def rate(metric, kind=6, bits=False):
        expr = f'({"8 * " if bits else ""}rate({selector(metric)}[5m])) and {fresh(metric)}'
        return observed(interfaces(expr, kind))

    def named(expr):
        # Join descriptions after rate/ratio calculations so comment changes do
        # not reset counters or affect arithmetic. Keep unnamed interfaces too.
        identity = 'job, instance, ifIndex, ifName'
        aliases = fresh('ifAlias', 'ifAlias!=""')
        names = f'label_join({aliases}, "interface", " · ", "ifAlias", "ifName")'
        fallback = f'label_replace(({expr}), "interface", "$1", "ifName", "(.*)")'
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
            description='Collection success only, not overall switch health. Telemetry older than 180 seconds is unknown.')
    mapping(p, {-1: ('Unknown', 'gray'), 0: ('Failed', 'red'), 1: ('Collecting', 'green')})
    add('SNMP uptime', [(observed(fresh('sysUpTime')), '')], 6, 0, 6, 4, unit='s', kind='stat',
        description='SNMP agent uptime in seconds; TimeTicks are converted by the collector.')
    add('RouterOS', [(observed(fresh('mtxrLicVersion')), '{{mtxrLicVersion}}')], 12, 0, 6, 4, kind='stat')['options']['textMode'] = 'name'
    add('Model', [(observed(fresh('mtxrBoardName')), '{{mtxrBoardName}}')], 18, 0, 6, 4, kind='stat')['options']['textMode'] = 'name'
    add('CPU usage', [(observed(fresh('hrProcessorLoad')), 'Processor {{hrDeviceIndex}}')], 0, 4, 8, unit='percent',
        description='Approximately one-minute non-idle percentage per logical processor. SNMP indexes identify processors.')
    memory = 'hrStorageDescr="main memory"'
    add('Memory usage', [(observed(f'100 * {fresh("hrStorageUsed", memory)} / ({fresh("hrStorageSize", memory)} > 0)'), 'Used')],
        8, 4, 8, unit='percent', description='Used/total allocation units for main memory only; excludes the system disk.')
    add('Temperature', [(observed(fresh('mtxrGaugeValue', 'mtxrGaugeUnit="1"')), '{{mtxrGaugeName}}')], 16, 4, 8, unit='celsius',
        description='RouterOS health gauges explicitly reporting Celsius, including CPU and SFP temperature sensors.')
    for kind, title, y in [(6, 'Port', 11), (161, 'Bond', 18)]:
        for direction, metric, x in [('receive', 'ifHCInOctets', 0), ('transmit', 'ifHCOutOctets', 12)]:
            add(title + ' ' + direction, [(named(rate(metric, kind, bits=True)), '{{interface}}')], x, y, unit='bps',
                description='Five-minute average bits/s per interface. Physical Ethernet ports and bonds are separate; '
                            'do not sum them or the two switches as unique traffic. Bridge and loopback counters are excluded.')
    p = table('Port link status', observed(interfaces(fresh('ifOperStatus'))), 0, 25, ['ifName', 'ifIndex', 'Value'])
    mapping(p, {1: ('Up', 'green'), 2: ('Down', 'yellow'), 3: ('Testing', 'yellow'), 4: ('Unknown', 'gray'),
                5: ('Dormant', 'yellow'), 6: ('Not present', 'gray'), 7: ('Lower layer down', 'yellow')})
    add('Port link speed', [(named(observed(interfaces(f'1000000 * {fresh("ifHighSpeed")}'))), '{{interface}}')],
        12, 25, unit='bps', description='Interface-reported link speed. ifHighSpeed uses millions of bits per second; zero means unknown/unavailable.')
    for direction, metric, x in [('receive', 'ifHCInOctets', 0), ('transmit', 'ifHCOutOctets', 12)]:
        speed = f'(1000000 * ({fresh("ifHighSpeed")} > 0))'
        add('Port ' + direction + ' utilization', [(named(f'100 * ({rate(metric, bits=True)}) / {speed}'), '{{interface}}')],
            x, 32, unit='percent', description='Per-direction traffic divided by current port speed. Zero or missing link speed shows gaps.')
    for title, rx, tx, x in [('Port errors', 'ifInErrors', 'ifOutErrors', 0), ('Port discards', 'ifInDiscards', 'ifOutDiscards', 12)]:
        add(title, [(named(rate(rx)), '{{interface}} RX'), (named(rate(tx)), '{{interface}} TX')], x, 39, unit='pps',
            description='Five-minute average packets/s from interface error/discard counters. Counter resets are handled by rate().')
    add('Fan speed', [(observed(fresh('mtxrGaugeValue', 'mtxrGaugeUnit="2"')), '{{mtxrGaugeName}}')], 0, 46, unit='rotrpm')
    p = add('Power supplies', [(observed(fresh('mtxrHlPowerSupplyState')), 'Primary'),
                              (observed(fresh('mtxrHlBackupPowerSupplyState')), 'Backup')], 12, 46, kind='stat',
            description='Legacy RouterOS PSU-OK booleans: 1=true, 0=false. Not OK can mean an unpowered supply; it is not proof of hardware failure.')
    mapping(p, {0: ('Not OK', 'yellow'), 1: ('OK', 'green')})
    table('Interface descriptions', observed(fresh('ifAlias')), 0, 53, ['ifName', 'ifAlias'], w=24)
    return {'uid': 'mikrotik-overview', 'title': 'MikroTik Switches', 'schemaVersion': 39, 'version': 1,
            'editable': False, 'tags': ['homelab', 'infrastructure', 'mikrotik'], 'timezone': 'browser',
            'refresh': '1m', 'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': [{'name': 'switch', 'label': 'Switch', 'type': 'custom', 'query': ','.join(SWITCHES),
                'current': {'text': SWITCHES[0], 'value': SWITCHES[0]},
                'options': [{'text': s, 'value': s, 'selected': s == SWITCHES[0]} for s in SWITCHES],
                'multi': False, 'includeAll': False, 'hide': 0, 'skipUrlSync': False}]},
            'annotations': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/mikrotik.json').write_text(json.dumps(build(), indent=2) + '\n')
