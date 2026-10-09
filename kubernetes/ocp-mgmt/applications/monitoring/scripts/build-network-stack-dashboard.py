#!/usr/bin/env python3
"""Arrange existing physical-port traffic queries in rack order."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
DEVICES = [
    ('pfsense', 'pfsense', 'pfSense', 'Physical interface'),
    ('mikrotik', 'crs317-b', 'crs317-b', 'Port'),
    ('mikrotik', 'crs317-a', 'crs317-a', 'Port'),
    ('unifi', 'usw-enterprise-48-poe', 'USW Enterprise 48 PoE', 'Port'),
]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/build-{name}-dashboard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build():
    panels = []
    for row, (job, instance, title, prefix) in enumerate(DEVICES):
        module = load(job)
        source = module.build() if job == 'pfsense' else module.build(instance)
        for column, (direction, label) in enumerate([('transmit', 'Send / TX'), ('receive', 'Receive / RX')]):
            panel = copy.deepcopy(next(p for p in source['panels'] if p['title'] == f'{prefix} {direction}'))
            panel.update(id=len(panels) + 1, title=f'{title} — {label}',
                         gridPos={'x': column * 12, 'y': row * 6, 'w': 12, 'h': 6})
            panel['description'] = (
                f'{label} from {title}’s perspective. One line per physical Ethernet port, '
                'using the interface alias where available. Five-minute average bits/s. '
                'LAG and VLAN counters are excluded to avoid counting the same traffic twice. '
                'Rack order does not imply a single forwarding path; compare aliases at each link’s endpoints. '
                'Axes autoscale independently. Missing, failed, or stale telemetry appears as gaps.')
            panel['links'] = [{'title': f'Open {title} dashboard',
                              'url': f'/d/{source["uid"]}' + (f'?var-switch={instance}' if job != 'pfsense' else '')}]
            panels.append(panel)
    return {'uid': 'network-stack', 'title': 'Network Stack',
            'description': 'Physical rack order. Send on the left, receive on the right; directions are device-relative.',
            'schemaVersion': 39, 'version': 1, 'editable': False,
            'tags': ['homelab', 'infrastructure', 'network'], 'timezone': 'browser',
            'refresh': '1m', 'time': {'from': 'now-6h', 'to': 'now'},
            'graphTooltip': 1, 'panels': panels, 'templating': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/network-stack.json').write_text(json.dumps(build(), indent=2) + '\n')
