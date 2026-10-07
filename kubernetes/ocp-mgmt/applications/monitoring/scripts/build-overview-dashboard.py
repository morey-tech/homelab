#!/usr/bin/env python3
"""Build a shared utilization dashboard using the existing device queries."""
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
        graph(uid, cpu, title + ' CPU usage', 0, y, legend=legend)
        p = graph(uid, memory, title + ' memory usage', 8, y, legend=legend)
        if uid == 'infrastructure':
            p['title'] = 'qnap-01 memory breakdown'
            p['targets'] = qnap.memory_targets()
            p['description'] = qnap.MEMORY_DESCRIPTION
            p['fieldConfig']['defaults']['decimals'] = 2
            p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'none', 'group': 'A'}
        if uid == 'ocp-home':
            p = graph(uid, 'GPU render utilization', 'OCP Home iGPU usage', 16, y, legend='Render / 3D')
            video = next(p for p in sources[uid]['panels'] if p['title'] == 'GPU video utilization')
            p['targets'].append(dict(p['targets'][0], refId='B',
                                     expr=video['targets'][0]['expr'], legendFormat='Video engine 0'))
            p['description'] = 'Intel iGPU render/3D and video engine 0 utilization, shown separately. Missing, failed, or stale telemetry appears as gaps.'
        elif uid == 'ocp-mgmt':
            graph(uid, 'GPU utilization', 'tr-gpu · RTX 3090 GPU utilization', 16, y, legend='tr-gpu · GPU 0')
        else:
            graph(uid, 'Shared-folder usage', 'qnap-01 shared-folder usage', 16, y, legend='{{share}}')

    return {'uid': 'homelab-overview', 'title': 'Homelab Overview',
            'tags': ['homelab', 'overview'], 'schemaVersion': 39, 'version': 1,
            'editable': False, 'timezone': 'browser', 'refresh': '30s',
            'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/overview.json').write_text(json.dumps(build(), indent=2) + '\n')
