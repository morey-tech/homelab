#!/usr/bin/env python3
"""Build a shared utilization dashboard using the existing device queries."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build():
    cluster = load('cluster_dashboard', 'build-dashboard.py')
    qnap = load('qnap_dashboard', 'build-qnap-dashboard.py')
    sources = {
        'ocp-home': cluster.build('ocp-home'),
        'ocp-mgmt': cluster.build('ocp-mgmt'),
        'infrastructure': qnap.build(),
    }
    panels = []

    def graph(uid, source_title, title, x, y, legend='{{instance}}'):
        source = next(p for p in sources[uid]['panels'] if p['title'] == source_title)
        p = cluster.panel(title, source['targets'][0]['expr'], x, y, 8, 7,
                          'timeseries', 'percent',
                          description='Utilization percentage. Missing, failed, or stale source telemetry appears as gaps. '
                                      + source.get('description', ''))
        p['id'] = len(panels) + 1
        p['datasource']['uid'] = uid
        p['targets'][0]['datasource']['uid'] = uid
        p['targets'][0]['legendFormat'] = legend
        p['targets'][0]['interval'] = '1m' if uid == 'infrastructure' else '30s'
        panels.append(p)
        return p

    for y, uid, title in [(0, 'ocp-home', 'OCP Home'), (7, 'ocp-mgmt', 'OCP Management'),
                          (14, 'infrastructure', 'qnap-01')]:
        cpu, memory = ('CPU usage', 'Memory in use') if uid == 'infrastructure' else ('Node CPU usage', 'Node memory usage')
        legend = 'qnap-01' if uid == 'infrastructure' else '{{instance}}'
        p = graph(uid, cpu, title + ' CPU usage', 0, y, legend=legend)
        if uid == 'infrastructure':
            p['title'] = 'qnap-01 CPU breakdown'
            p['targets'] = qnap.cpu_targets()
            p['description'] = ('Overall CPU usage is shown by default. Processor series remain available '
                                'in the legend; Ctrl/Cmd-click a processor to add it to the graph. '
                                + qnap.CPU_DESCRIPTION)
            p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
            # Use Grafana's saved legend selection so legend clicks can toggle
            # processors back on (a plain hideFrom override would keep hiding them).
            p['fieldConfig']['overrides'].append({
                '__systemRef': 'hideSeriesFrom',
                'matcher': {'id': 'byNames', 'options': {
                    'mode': 'exclude', 'names': ['Overall (NAS)'],
                    'prefix': 'All except:', 'readOnly': True}},
                'properties': [{'id': 'custom.hideFrom', 'value': {
                    'viz': True, 'legend': False, 'tooltip': False}}]})
        p = graph(uid, memory, title + ' memory usage', 8, y, legend=legend)
        if uid == 'infrastructure':
            p['title'] = 'qnap-01 memory breakdown'
            p['targets'] = qnap.memory_targets()
            p['description'] = qnap.MEMORY_DESCRIPTION
            p['fieldConfig']['defaults']['decimals'] = 2
            p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
        if uid != 'infrastructure':
            p = copy.deepcopy(next(p for p in sources[uid]['panels'] if p['title'] == 'Node network receive'))
            p['id'] = len(panels) + 1
            p['title'] = title + ' network traffic'
            p['gridPos'] = {'x': 16, 'y': y, 'w': 8, 'h': 7}
            scope = ('OCP Home bond0 only, excluding member ports.' if uid == 'ocp-home' else
                     'OCP Management physical Ethernet interfaces summed per node. '
                     'These are node interface totals, not unique cluster-wide traffic; inter-node traffic appears at both endpoints.')
            p['description'] = ('Receive and transmit traffic per node in bits per second, averaged over five minutes. '
                                + scope + ' Missing, failed, or stale telemetry appears as gaps. '
                                'Interface details are available on the cluster dashboard.')
            p['targets'] = []
            for ref, direction, label in [('A', 'receive', 'Receive'), ('B', 'transmit', 'Transmit')]:
                source = next(p for p in sources[uid]['panels'] if p['title'] == 'Node network ' + direction)
                query = copy.deepcopy(source['targets'][0])
                query.update(refId=ref, expr=f'sum by (instance) ({query["expr"]})',
                             legendFormat='{{instance}} · ' + label, interval='30s')
                p['targets'].append(query)
            p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
            panels.append(p)
        else:
            p = copy.deepcopy(next(p for p in sources[uid]['panels'] if p['title'] == 'Network receive'))
            p['id'] = len(panels) + 1
            p['title'] = 'qnap-01 bond0 network traffic'
            p['gridPos'] = {'x': 16, 'y': y, 'w': 8, 'h': 7}
            p['description'] = ('Receive and transmit traffic on qnap-01 bond0 only, in bits per second. '
                                'Five-minute average rates from 64-bit byte counters. '
                                'Missing, failed, or stale collection appears as gaps.')
            p['targets'] = [dict(p['targets'][0], refId=ref, legendFormat=legend,
                                 expr=qnap.network_rate(metric, interface='bond0'))
                            for ref, metric, legend in [('A', 'ifHCInOctets', 'Receive'),
                                                        ('B', 'ifHCOutOctets', 'Transmit')]]
            panels.append(p)

    return {'uid': 'homelab-overview', 'title': 'Homelab Overview',
            'tags': ['homelab', 'overview'], 'schemaVersion': 39, 'version': 1,
            'editable': False, 'timezone': 'browser', 'refresh': '30s',
            'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/overview.json').write_text(json.dumps(build(), indent=2) + '\n')
