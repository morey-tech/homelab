#!/usr/bin/env python3
"""Check rack ordering, directions, query reuse, and dashboard provisioning."""
import importlib.util
import json
from pathlib import Path
import sys
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stack', ROOT / 'scripts/build-network-stack-dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
dashboard = module.build()
assert json.loads((ROOT / 'dashboards/network-stack.json').read_text()) == dashboard
assert len(dashboard['panels']) == 8
assert len({p['id'] for p in dashboard['panels']}) == 8
expected_devices = [('pfsense', 'pfsense'), ('mikrotik', 'crs317-b'),
                    ('mikrotik', 'crs317-a'), ('unifi', 'usw-enterprise-48-poe')]
for row, (job, instance) in enumerate(expected_devices):
    source = module.load(job)
    source = source.build() if job == 'pfsense' else source.build(instance)
    for column, (direction, metric) in enumerate([('transmit', 'ifHCOutOctets'), ('receive', 'ifHCInOctets')]):
        panel = dashboard['panels'][2 * row + column]
        assert panel['gridPos'] == {'x': 12 * column, 'y': 6 * row, 'w': 12, 'h': 6}
        title = ('Physical interface ' if job == 'pfsense' else 'Port ') + direction
        original = next(p for p in source['panels'] if p['title'] == title)
        assert panel['targets'] == original['targets'], 'Reuse the tested physical-port queries unchanged'
        assert panel['fieldConfig'] == original['fieldConfig']
        assert panel['fieldConfig']['defaults']['unit'] == 'bps'
        for target in panel['targets']:
            assert metric in target['expr'] and f'instance="{instance}"' in target['expr']
            assert target['datasource']['uid'] == 'infrastructure'
            assert target['legendFormat'] == '{{interface}}'
            assert '$switch' not in target['expr']

kustomization = yaml.safe_load((ROOT / 'kustomization.yaml').read_text())
config = next(c for c in kustomization['configMapGenerator'] if c['name'] == 'grafana-network-stack-dashboard')
assert config['files'] == ['dashboards/network-stack.json']
deployment = yaml.safe_load((ROOT / 'grafana.yaml').read_text())
volume = next(v for v in deployment['spec']['template']['spec']['volumes'] if v['name'] == 'dashboards')
assert {'configMap': {'name': config['name']}} in volume['projected']['sources']
print('Network stack: rack order, TX/RX placement, device isolation, query reuse, generation, and provisioning passed')
