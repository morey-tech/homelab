#!/usr/bin/env python3
"""Test pfSense dashboard units, missing data, interface selection, and aliases."""
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
spec = importlib.util.spec_from_file_location('pfsense', ROOT / 'scripts/build-pfsense-dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
dashboard = module.build()
assert json.loads((ROOT / 'dashboards/pfsense.json').read_text()) == dashboard
panels = {p['title']: p for p in dashboard['panels']}
LABELS = 'job="pfsense",instance="pfsense"'
PORT = 'ifIndex="5",ifName="ix0"'
RESULT = '{' + LABELS + ',' + PORT + ',interface="ix0"}'


def sample(metric, values, extra='', instance='pfsense'):
    labels = LABELS.replace('instance="pfsense"', f'instance="{instance}"')
    return {'series': metric + '{' + labels + (',' + extra if extra else '') + '}', 'values': values}


def check(title, value=None, labels=RESULT, ref=0):
    return {'expr': panels[title]['targets'][ref]['expr'], 'eval_time': '5m',
            'exp_samples': [] if value is None else [{'labels': labels, 'value': value}]}


def case(name, series, checks):
    return {'name': name, 'interval': '1m', 'input_series': series, 'promql_expr_test': checks}


healthy = sample('up', '1+0x5')
traffic = sample('ifHCInOctets', '0+6000x5', PORT)
tests = [case('all queries parse and absent data stays unknown', [], [
    {'expr': t['expr'], 'eval_time': '5m', 'exp_samples': [{'labels': '{}', 'value': -1}] if p['title'] == 'SNMP collection' else []}
    for p in dashboard['panels'] for t in p['targets']]),
    case('receive bytes become bits', [healthy, traffic], [check('Physical interface receive', 800)]),
    case('transmit bytes become bits', [healthy, sample('ifHCOutOctets', '0+12000x5', PORT)], [check('Physical interface transmit', 1600)]),
    case('idle is zero', [healthy, sample('ifHCInOctets', '0+0x5', PORT)], [check('Physical interface receive', 0)]),
    case('counter reset', [healthy, sample('ifHCInOctets', '0 6000 12000 0 6000 12000', PORT)], [check('Physical interface receive', 600)]),
    case('one sample cannot produce a rate', [healthy, sample('ifHCInOctets', '_ _ _ _ _ 6000', PORT)], [check('Physical interface receive')]),
    case('failed collection hides traffic', [sample('up', '1 1 1 1 1 0'), traffic], [check('Physical interface receive')]),
    case('stale collection is unknown', [sample('up', '1 1 1 _ _ _'), traffic], [check('Physical interface receive'), check('SNMP collection', -1, '{}')]),
    case('stale counter remains missing', [healthy, sample('ifHCInOctets', '0 6000 12000 _ _ _', PORT)], [check('Physical interface receive')]),
    case('live alias names a port', [healthy, traffic, sample('ifAlias', '1+0x5', PORT + ',ifAlias="Switch A"')],
         [check('Physical interface receive', 800, RESULT.replace('interface="ix0"', 'interface="Switch A · ix0"'))]),
    case('stale alias falls back to name', [healthy, traffic, sample('ifAlias', '1 1 1 _ _ _', PORT + ',ifAlias="Old"')],
         [check('Physical interface receive', 800)]),
    case('another device cannot supply aliases', [healthy, traffic, sample('ifAlias', '1+0x5', PORT + ',ifAlias="Other"', 'other')],
         [check('Physical interface receive', 800)]),
    case('failed selected device cannot borrow another success', [sample('up', '0+0x5'), traffic, sample('up', '1+0x5', instance='other')],
         [check('Physical interface receive')]),
    case('error counters are packet rates', [healthy, sample('ifInErrors', '0+60x5', PORT)], [check('Interface errors', 1)]),
    case('link speed is millions of bits per second', [healthy, sample('ifHighSpeed', '10000+0x5', PORT)], [check('Physical link speed', 1e10)]),
    case('confirmed WAN assignment labels ix2', [healthy,
         sample('ifHCInOctets', '0+6000x5', 'ifIndex="7",ifName="ix2"')],
         [check('Physical interface receive', 800, '{' + LABELS + ',ifIndex="7",ifName="ix2",interface="WAN · ix2"}')]),
]
for interface in ['lagg0', 'lagg0.6', 'tun_wg0', 'tailscale0', 'pppoe1']:
    port = f'ifIndex="19",ifName="{interface}"'
    label = module.INTERFACE_NAMES.get(interface)
    display = label + ' · ' + interface if label else interface
    result = '{' + LABELS + ',' + port + ',interface=' + json.dumps(display, ensure_ascii=False) + '}'
    tests.append(case('logical interface stays separate: ' + interface,
        [healthy, sample('ifHCInOctets', '0+6000x5', port)],
        [check('Physical interface receive'), check('Logical interface receive', 800, result)]))
tests.append(case('empty live alias uses configured VLAN description', [healthy,
    sample('ifHCInOctets', '0+6000x5', 'ifIndex="15",ifName="lagg0.6"'),
    sample('ifAlias', '1+0x5', 'ifIndex="15",ifName="lagg0.6",ifAlias=""')],
    [check('Logical interface receive', 800, '{' + LABELS + ',ifIndex="15",ifName="lagg0.6",interface="RH_LAB · lagg0.6"}')]))
tests.append(case('live alias overrides configured VLAN description', [healthy,
    sample('ifHCInOctets', '0+6000x5', 'ifIndex="15",ifName="lagg0.6"'),
    sample('ifAlias', '1+0x5', 'ifIndex="15",ifName="lagg0.6",ifAlias="New lab"')],
    [check('Logical interface receive', 800, '{' + LABELS + ',ifIndex="15",ifName="lagg0.6",interface="New lab · lagg0.6"}')]))
tests.append(case('loopback logging and sync excluded', [healthy] + [
    sample('ifHCInOctets', '0+6000x5', f'ifIndex="{i}",ifName="{name}"')
    for i, name in enumerate(['lo0', 'enc0', 'pflog0', 'pfsync0', 'lagg0x6'])],
    [check('Physical interface receive'), check('Logical interface receive')]))
memory = 'hrStorageDescr="Physical memory",hrStorageIndex="1"'
for total, expected in [(1000, 25), (0, None)]:
    tests.append(case('memory denominator ' + str(total), [healthy,
        sample('hrStorageSize', str(total)+'+0x5', memory), sample('hrStorageUsed', '250+0x5', memory),
        sample('hrStorageSize', '1000+0x5', 'hrStorageDescr="Virtual memory",hrStorageIndex="3"'),
        sample('hrStorageUsed', '999+0x5', 'hrStorageDescr="Virtual memory",hrStorageIndex="3"')],
        [check('Memory usage', expected, '{'+LABELS+','+memory+'}')]))
tests.append(case('memory KiB converted to bytes', [healthy, sample('memTotalReal', '1000+0x5'), sample('memAvailReal', '750+0x5')],
    [check('Memory breakdown', 256000, '{'+LABELS+'}'), check('Memory breakdown', 768000, '{'+LABELS+'}', ref=1)]))
tests.append(case('filesystem excludes pseudo filesystems and guards zero totals', [healthy] + [
    sample(metric, value+'+0x5', f'hrStorageDescr="{path}",hrStorageIndex="{i}"')
    for i, path in enumerate(['/', '/dev', '/var/run', '/empty'])
    for metric, value in [('hrStorageUsed', '25'), ('hrStorageSize', '0' if path == '/empty' else '100')]],
    [check('Filesystem usage', 25, '{'+LABELS+',hrStorageDescr="/",hrStorageIndex="0"}')]))
tests.append(case('CPU average uses cores', [healthy,
    sample('hrProcessorLoad', '20+0x5', 'hrDeviceIndex="1"'), sample('hrProcessorLoad', '40+0x5', 'hrDeviceIndex="2"')],
    [check('CPU usage', 30, '{'+LABELS+'}')]))
with tempfile.TemporaryDirectory(prefix='pfsense-promql-') as directory:
    path = Path(directory) / 'tests.yml'
    path.write_text(yaml.safe_dump({'rule_files': [], 'evaluation_interval': '1m', 'tests': tests}))
    subprocess.run([os.environ.get('PROMTOOL', 'promtool'), 'test', 'rules', str(path)], check=True)
print(f'Validated {len(dashboard["panels"])} panels and {len(tests)} telemetry scenarios.')
