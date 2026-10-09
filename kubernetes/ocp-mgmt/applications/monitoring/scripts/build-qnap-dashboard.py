#!/usr/bin/env python3
"""Build the QNAP dashboard from the curated QuTS hero SNMP module."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = {'type': 'prometheus', 'uid': 'infrastructure'}
LABELS = 'job="qnap",instance="qnap-01"'


def fresh(metric):
    selector = f'{metric}{{{LABELS}}}'
    return f'({selector} and (time() - timestamp({selector}) < 180))'


UP = f'({fresh("up")} == 1)'


def observed(expr):
    return f'({expr}) and on(job, instance) {UP}'


CPU_DESCRIPTION = (
    'Overall utilization is the NAS-reported value. Each processor line is its '
    'approximately one-minute non-idle percentage from HOST-RESOURCES-MIB. '
    'Processor labels are SNMP device indexes, not physical-core or operating-system CPU numbers. '
    'The two sources may use different averaging windows. Missing, failed, or stale telemetry appears as gaps. '
    'User/system/I/O-wait counters and load averages were not returned by the SNMP probe.'
)


def cpu_targets():
    return [{'refId': ref, 'datasource': DS, 'expr': observed(fresh(metric)),
             'instant': False, 'range': True, 'legendFormat': label, 'editorMode': 'code',
             'interval': '1m'} for ref, metric, label in [
        ('A', 'systemCPU_Usage', 'Overall (NAS)'),
        ('B', 'hrProcessorLoad', 'Processor {{hrDeviceIndex}}')]]


MEMORY_DESCRIPTION = (
    'Each line is a percentage of total memory. Used, available, free, cache, and buffers '
    'are separate NAS-reported counters. These values overlap; do not add or stack them. '
    'The MIB does not identify cache as ZFS ARC, so ARC is not inferred from these counters. '
    'Missing, failed, or stale telemetry appears as gaps.'
)


def memory_targets():
    total = f'({fresh("systemTotalMem")} > 0)'
    queries = [(label, f'100 * {fresh(metric)} / {total}') for label, metric in [
        ('Used (NAS)', 'systemUsedMemory'), ('Available', 'systemAvailableMem'),
        ('Free', 'systemFreeMem'), ('Cache (NAS)', 'systemCacheMemory'),
        ('Buffers', 'systemBufferMemory')]]
    return [{'refId': chr(ord('A') + i), 'datasource': DS, 'expr': observed(expr),
             'instant': False, 'range': True, 'legendFormat': label, 'editorMode': 'code',
             'interval': '1m'} for i, (label, expr) in enumerate(queries)]


def network_rate(metric, interface='(eth|bond)[0-9]+([.][0-9]+)?'):
    selector = f'{metric}{{{LABELS},ifName=~{json.dumps(interface)}}}'
    return observed(f'(8 * rate({selector}[5m])) and {fresh(metric)}')


def capacity_summary(capacity_metric, free_metric):
    total, free = fresh(capacity_metric), fresh(free_metric)
    # Require a coherent pair. Missing/zero/invalid capacity must not look empty.
    valid = f'({total} > 0) and ({free} >= 0) and ({free} <= {total})'
    used = f'({total} - {free}) and ({valid})'
    values = [('Used', used), ('Total', f'(0 + {total}) and ({valid})'),
              ('Used %', f'100 * ({used}) / ({total} > 0)')]
    return ' or '.join(f'label_replace(({observed(expr)}), "capacity_stat", {json.dumps(name)}, "__name__", ".*")'
                       for name, expr in values)


def build():
    panels = []

    def add(title, expr, x, y, w=6, h=4, kind='stat', unit='short', legend='', description=''):
        defaults = {'unit': unit, 'noValue': 'Unknown', 'decimals': 1,
                    'color': {'mode': 'palette-classic'}}
        panel = {'id': len(panels) + 1, 'title': title, 'type': kind,
                 'description': description, 'datasource': DS,
                 'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
                 'fieldConfig': {'defaults': defaults, 'overrides': []},
                 'targets': [{'refId': 'A', 'datasource': DS, 'expr': expr,
                              'instant': kind != 'timeseries', 'range': kind == 'timeseries',
                              'legendFormat': legend, 'editorMode': 'code'}]}
        if kind == 'stat':
            panel['options'] = {'reduceOptions': {'calcs': ['last'], 'fields': '', 'values': False},
                                'colorMode': 'value', 'graphMode': 'none', 'textMode': 'auto'}
        elif kind == 'timeseries':
            defaults.update({'min': 0, 'custom': {'drawStyle': 'line', 'lineWidth': 2,
                                                 'fillOpacity': 10, 'spanNulls': False}})
            if unit == 'percent':
                defaults['max'] = 100
            panel['options'] = {'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True},
                                'tooltip': {'mode': 'multi', 'sort': 'desc'}}
        elif kind == 'table':
            panel['targets'][0]['format'] = 'table'
            panel['options'] = {'showHeader': True, 'cellHeight': 'sm'}
        panels.append(panel)
        return panel

    def mapping(panel, values):
        panel['fieldConfig']['defaults']['mappings'] = [
            {'type': 'value', 'options': {str(k): {'text': text, 'color': color}
                                         for k, (text, color) in values.items()}}]

    def table(title, metric, x, y, columns):
        p = add(title, observed(fresh(metric)), x, y, 12, 6, 'table')
        p['transformations'] = [{'id': 'filterFieldsByName', 'options': {'include': {'names': columns}}}]

    p = add('SNMP collection', f'{fresh("up")} or on() vector(-1)', 0, 0,
            description='Collection status only, not NAS health. Unknown when telemetry is missing or older than 180 seconds.')
    mapping(p, {-1: ('Unknown', 'gray'), 0: ('Failed', 'red'), 1: ('Collecting', 'green')})
    add('NAS uptime', observed(fresh('sysUptime')), 6, 0, unit='s')
    add('CPU usage', observed(fresh('systemCPU_Usage')), 12, 0, unit='percent')
    memory = f'100 * (1 - {fresh("systemAvailableMem")} / ({fresh("systemTotalMem")} > 0))'
    add('Memory in use', observed(memory), 18, 0, unit='percent',
        description='100 × (1 − available / total). Includes only memory unavailable for new workloads; no byte-unit assumption.')
    pool_used = f'{fresh("storagepoolCapacity")} - {fresh("storagepoolFreeSize")}'
    add('Pool used capacity', observed(pool_used), 0, 4, 12, 6, 'timeseries', 'bytes', 'Pool {{pool_id}}',
        'Pool capacity minus free space reported by QuTS hero. Do not sum share usage to derive this value.')
    add('Pool usage', observed(f'100 * ({pool_used}) / ({fresh("storagepoolCapacity")} > 0)'),
        12, 4, 12, 6, 'timeseries', 'percent', 'Pool {{pool_id}}')
    add('Pool capacity', observed(fresh('storagepoolCapacity')), 0, 10, 8, unit='bytes', legend='Pool {{pool_id}}')
    add('Pool free space', observed(fresh('storagepoolFreeSize')), 8, 10, 8, unit='bytes', legend='Pool {{pool_id}}')
    p = add('Pool state', observed(fresh('storagepoolStatus')), 16, 10, 8, legend='Pool {{pool_id}}',
            description='QuTS hero state codes from NAS.mib; unknown codes remain numeric and are not treated as Ready.')
    states = {-4: 'SED locked', -3: 'Error', -2: 'Not ready', -1: 'Warning', 0: 'Ready',
              1: 'Resilvering', 2: 'Exporting', 3: 'Removing', 4: 'Scrubbing', 5: 'Creating',
              6: 'SED locking', 7: 'SED unlocking', 8: 'Stopping', 9: 'Stopped',
              10: 'Starting', 11: 'Importing', 12: 'Read only', 13: 'Pruning', 14: 'Tuning', 255: 'Unknown'}
    mapping(p, {code: (text, 'green' if code == 0 else 'gray' if code == 255 else 'red' if code < -1 else 'yellow')
                for code, text in states.items()})
    share_used = f'{fresh("sharedFolderCapacity")} - {fresh("sharedFolderFreeSize")}'
    add('Shared-folder used capacity', observed(share_used), 0, 14, 12, 6, 'timeseries', 'bytes', '{{share}}',
        'Logical shared-folder capacity minus free space. Allocation, snapshots, and compression can differ from pool accounting.')
    add('Shared-folder usage', observed(f'100 * ({share_used}) / ({fresh("sharedFolderCapacity")} > 0)'),
        12, 14, 12, 6, 'timeseries', 'percent', '{{share}}')
    table('Shared-folder status', 'sharedFolderStatus', 0, 20, ['share', 'sharedFolderStatus'])
    table('RAID status', 'raidStatus', 12, 20, ['raid_id', 'raid_name', 'raid_level', 'raidStatus'])
    table('Disk status', 'diskStatus', 0, 26, ['disk_id', 'model', 'diskStatus'])
    add('Disk temperature', observed(f'{fresh("diskTemperature")} >= 0'), 12, 26, 12, 6,
        'timeseries', 'celsius', 'Disk {{disk_id}}', 'Negative values are treated as unavailable sensors.')
    add('CPU temperature', observed(f'{fresh("cpuTemperature")} >= 0'), 0, 32, unit='celsius')
    add('System temperature', observed(f'{fresh("systemTemperature")} >= 0'), 6, 32, unit='celsius')
    p = add('Power supply', observed(fresh('sysPowerStatus')), 12, 32)
    mapping(p, {-1: ('Failed', 'red'), 0: ('OK', 'green')})
    add('Fan speed', observed(fresh('sysFanSpeed')), 18, 32, unit='rotrpm', legend='{{fan}}')
    p = add('Memory breakdown', memory_targets()[0]['expr'], 0, 36, 24, 7,
            'timeseries', 'percent', description=MEMORY_DESCRIPTION)
    p['targets'] = memory_targets()
    p['fieldConfig']['defaults']['decimals'] = 2
    p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
    p = add('CPU breakdown', cpu_targets()[0]['expr'], 0, 43, 24, 7,
            'timeseries', 'percent', description=CPU_DESCRIPTION)
    p['targets'] = cpu_targets()
    p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
    for x, direction, metric in [(0, 'receive', 'ifHCInOctets'), (12, 'transmit', 'ifHCOutOctets')]:
        p = add('Network ' + direction, network_rate(metric), x, 50, 12, 7,
                'timeseries', 'bps', '{{ifName}} ({{ifIndex}})',
                'Five-minute average bits per second from 64-bit interface byte counters. '
                'Shows Ethernet ports, bonds, and their VLANs individually. Do not sum these lines: '
                'traffic can appear on both a bond and its member ports or VLANs. '
                'Loopback and virtual bridges are excluded. Requires at least two samples; '
                'failed or stale collection appears as gaps.')
        p['targets'][0]['interval'] = '1m'
        p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
    # Keep existing panel IDs and insert the current capacity summaries below
    # the health row, before the historical capacity graphs.
    for p in panels:
        if p['gridPos']['y'] >= 4:
            p['gridPos']['y'] += 7
    for title, capacity, free, identity, label, x, widths in [
        ('Pool capacity overview', 'storagepoolCapacity', 'storagepoolFreeSize', 'pool_id', 'Pool', 0, (50, 84, 87)),
        ('Shared-folder capacity overview', 'sharedFolderCapacity', 'sharedFolderFreeSize', 'share', 'Shared folder', 12, (111, 87, 87)),
    ]:
        p = add(title, capacity_summary(capacity, free), x, 4, 12, 7, 'table', 'bytes',
                description='Current used and total capacity with a 0–100% usage bar for each item. Used = total minus free. '
                            'Pool and logical shared-folder accounting differ; do not sum shares to infer pool usage. '
                            'Missing, stale, failed, zero-total, or inconsistent telemetry is omitted, not shown as empty storage.')
        # Keep labeled instant frames so the explicit transformations work
        # independently of Prometheus' frontend table-format conversion.
        p['targets'][0]['format'] = 'time_series'
        p['transformations'] = [
            {'id': 'labelsToFields', 'options': {'mode': 'columns', 'valueLabel': 'capacity_stat'}},
            {'id': 'merge', 'options': {}},
            {'id': 'filterFieldsByName', 'options': {'include': {'names': [identity, 'Used', 'Total', 'Used %']}}},
            {'id': 'organize', 'options': {'indexByName': {identity: 0, 'Used': 1, 'Total': 2, 'Used %': 3},
                                          'renameByName': {identity: label}}},
        ]
        p['fieldConfig']['defaults']['decimals'] = 2
        p['options']['sortBy'] = [{'displayName': 'Used %', 'desc': True}]
        # Add 10% to the widths fitted in Grafana; the bar fills the rest.
        p['fieldConfig']['overrides'] = [
            {'matcher': {'id': 'byName', 'options': label}, 'properties': [
                {'id': 'unit', 'value': 'string'},
                {'id': 'custom.width', 'value': round(widths[0] * 1.1)},
            ]},
            *[{'matcher': {'id': 'byName', 'options': name},
               'properties': [{'id': 'custom.width', 'value': round(width * 1.1)}]}
              for name, width in zip(['Used', 'Total'], widths[1:])],
            {'matcher': {'id': 'byName', 'options': 'Used %'}, 'properties': [
                {'id': 'unit', 'value': 'percent'}, {'id': 'decimals', 'value': 1},
                {'id': 'min', 'value': 0}, {'id': 'max', 'value': 100},
                {'id': 'color', 'value': {'mode': 'thresholds'}},
                {'id': 'thresholds', 'value': {'mode': 'absolute', 'steps': [
                    {'color': 'green', 'value': None}, {'color': 'yellow', 'value': 80}, {'color': 'red', 'value': 90}]}},
                {'id': 'custom.cellOptions', 'value': {'type': 'gauge', 'mode': 'basic', 'valueDisplayMode': 'text'}},
            ]},
        ]
    return {'uid': 'qnap-overview', 'title': 'QNAP Overview', 'schemaVersion': 39, 'version': 1,
            'editable': False, 'tags': ['homelab', 'infrastructure', 'qnap'], 'timezone': 'browser',
            'refresh': '1m', 'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': []}, 'annotations': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


def provisioned_dashboard():
    """Parameterize the detailed dashboard; overview queries stay on qnap-01."""
    dashboard = build()
    for panel in dashboard['panels']:
        for target in panel['targets']:
            target['expr'] = target['expr'].replace('instance="qnap-01"', 'instance="$nas"')
    dashboard['templating']['list'] = [{
        'name': 'nas', 'label': 'NAS', 'type': 'custom', 'query': 'qnap-01,qnap-02',
        'current': {'text': 'qnap-01', 'value': 'qnap-01'},
        'options': [{'text': name, 'value': name, 'selected': name == 'qnap-01'}
                    for name in ['qnap-01', 'qnap-02']],
        'multi': False, 'includeAll': False, 'hide': 0, 'skipUrlSync': False}]
    return dashboard


if __name__ == '__main__':
    (ROOT / 'dashboards/qnap.json').write_text(json.dumps(provisioned_dashboard(), indent=2) + '\n')
