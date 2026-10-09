#!/usr/bin/env python3
"""Verify UniFi dashboard generation, rates, freshness, and device isolation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('unifi', ROOT / 'scripts/build-unifi-dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert json.loads((ROOT / 'dashboards/unifi.json').read_text()) == module.build()
dashboard = module.build('usw-enterprise-48-poe')
assert len({p['id'] for p in dashboard['panels']}) == len(dashboard['panels'])
for i, p in enumerate(dashboard['panels']):
    a = p['gridPos']
    assert 0 <= a['x'] < a['x'] + a['w'] <= 24 and a['h'] > 0
    for q in dashboard['panels'][i+1:]:
        b = q['gridPos']
        assert not (a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w'] and
                    a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h']), (p['title'], q['title'])

panels = {p['title']: p for p in dashboard['panels']}
LABELS = 'job="unifi",instance="usw-enterprise-48-poe"'
PORT = 'ifIndex="2",ifName="0/1"'
PORT_RESULT = '{' + LABELS + ',' + PORT + ',interface="0/1"}'
NAMED_RESULT = '{' + LABELS + ',' + PORT + ',interface="ms-02 member 1 · 0/1"}'


def sample(metric, values, extra='', switch='usw-enterprise-48-poe'):
    labels = LABELS.replace('usw-enterprise-48-poe', switch)
    return {'series': metric + '{' + labels + (',' + extra if extra else '') + '}', 'values': values}


def check(title, value=None, labels=PORT_RESULT, at='5m', ref=0):
    return {'expr': panels[title]['targets'][ref]['expr'], 'eval_time': at,
            'exp_samples': [] if value is None else [{'labels': labels, 'value': value}]}


def case(name, series, checks):
    return {'name': name, 'interval': '1m', 'input_series': series, 'promql_expr_test': checks}


healthy = sample('up', '1+0x5')
physical = sample('ifType', '6+0x5', PORT)
traffic = sample('ifHCInOctets', '0+6000x5', PORT)
alias = sample('ifAlias', '1+0x5', PORT + ',ifAlias="ms-02 member 1"')
tests = [case('all queries parse and absent telemetry stays unknown', [], [
    {'expr': t['expr'], 'eval_time': '5m', 'exp_samples': [{'labels': '{}', 'value': -1}] if p['title'] == 'SNMP collection' else []}
    for p in dashboard['panels'] for t in p['targets']]),
    case('convert bytes/s to bits/s with independent directions', [healthy, physical, traffic,
         sample('ifHCOutOctets', '0+12000x5', PORT)], [check('Port receive', 800), check('Port transmit', 1600)]),
    case('alias names traffic without changing values', [healthy, physical, traffic, alias],
         [check('Port receive', 800, NAMED_RESULT)]),
    case('empty alias falls back to name', [healthy, physical, traffic,
         sample('ifAlias', '1+0x5', PORT + ',ifAlias=""')], [check('Port receive', 800)]),
    case('stale alias falls back without hiding traffic', [healthy, physical, traffic,
         sample('ifAlias', '1 1 1 _ _ _', PORT + ',ifAlias="old description"')], [check('Port receive', 800)]),
    case('alias on another switch cannot name this port', [healthy, physical, traffic,
         sample('ifAlias', '1+0x5', PORT + ',ifAlias="other server"', 'other-switch')], [check('Port receive', 800)]),
    case('alias on another interface cannot name this port', [healthy, physical, traffic,
         sample('ifAlias', '1+0x5', 'ifIndex="3",ifName="0/2",ifAlias="other server"')], [check('Port receive', 800)]),
    case('comment change preserves counter history', [healthy, physical, traffic,
         sample('ifAlias', '1 1 1 stale _ _', PORT + ',ifAlias="old description"'),
         sample('ifAlias', '_ _ _ 1 1 1', PORT + ',ifAlias="ms-02 member 1"')], [check('Port receive', 800, NAMED_RESULT)]),
    case('alias preserves utilization arithmetic', [healthy, physical, traffic, alias,
         sample('ifHighSpeed', '10000+0x5', PORT)], [check('Port receive utilization', .000008, NAMED_RESULT)]),
    case('bond aliases name server traffic', [healthy, sample('ifType', '161+0x5', PORT), traffic, alias],
         [check('Port receive'), check('LAG receive', 800, NAMED_RESULT)]),
    case('idle ports remain a valid zero', [healthy, physical, sample('ifHCInOctets', '0+0x5', PORT)], [check('Port receive', 0)]),
    case('handle counter resets', [healthy, physical, sample('ifHCInOctets', '0 6000 12000 0 6000 12000', PORT)], [check('Port receive', 600)]),
    case('failed scrape hides old counters', [sample('up', '1 1 1 1 1 0'), physical, traffic], [check('Port receive')]),
    case('stopped collector is unknown', [sample('up', '1 1 1 _ _ _'), physical, traffic], [check('Port receive'), check('SNMP collection', -1, '{}')]),
    case('stale counters stay missing despite fresh scrape', [healthy, physical, sample('ifHCInOctets', '0 6000 12000 _ _ _', PORT)], [check('Port receive')]),
    case('stale interface classification cannot revive ports', [healthy, traffic, sample('ifType', '6 6 6 _ _ _', PORT)], [check('Port receive')]),
    case('rate requires two samples', [healthy, physical, sample('ifHCInOctets', '_ _ _ _ _ 6000', PORT)], [check('Port receive')]),
    case('link-speed units are Mbit/s', [healthy, physical, traffic, sample('ifHighSpeed', '10000+0x5', PORT)], [check('Port receive utilization', .000008)]),
    case('zero link speed hides utilization', [healthy, physical, traffic, sample('ifHighSpeed', '0+0x5', PORT)], [check('Port receive utilization')]),
    case('bonds are separate from physical ports', [healthy, sample('ifType', '161+0x5', PORT), traffic], [check('Port receive'), check('LAG receive', 800)]),
    case('same interface index on another switch is isolated', [healthy, physical, traffic,
         sample('up', '1+0x5', switch='other-switch'), sample('ifType', '6+0x5', PORT, 'other-switch'),
         sample('ifHCInOctets', '0+600000x5', PORT, 'other-switch')], [check('Port receive', 800)]),
    case('another switch success cannot hide selected switch failure', [sample('up', '0+0x5'), physical, traffic,
         sample('up', '1+0x5', switch='other-switch')], [check('Port receive')]),
]

with tempfile.TemporaryDirectory(prefix='unifi-promql-') as directory:
    path = Path(directory) / 'tests.yml'
    path.write_text(yaml.safe_dump({'rule_files': [], 'evaluation_interval': '1m', 'tests': tests}))
    subprocess.run([os.environ.get('PROMTOOL', 'promtool'), 'test', 'rules', str(path)], check=True)
print(f'Validated {len(dashboard["panels"])} panels and {len(tests)} telemetry scenarios.')
