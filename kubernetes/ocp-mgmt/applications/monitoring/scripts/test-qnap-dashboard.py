#!/usr/bin/env python3
"""Check dashboard reproducibility, PromQL, and telemetry-loss behavior."""
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
spec = importlib.util.spec_from_file_location('qnap', ROOT / 'scripts/build-qnap-dashboard.py')
qnap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qnap)
dashboard = qnap.build()
assert json.loads((ROOT / 'dashboards/qnap.json').read_text()) == dashboard


def sample(metric, values, labels=''):
    extra = ',' + labels if labels else ''
    return {'series': f'{metric}{{{qnap.LABELS}{extra}}}', 'values': values}


def check(expr, expected=None, at='1m'):
    return {'expr': expr, 'eval_time': at, 'exp_samples': expected or []}


panels = {p['title']: p['targets'][0]['expr'] for p in dashboard['panels']}
tests = [
    {'name': 'all dashboard queries parse and missing telemetry remains unknown',
     'interval': '1m', 'input_series': [],
     'promql_expr_test': [check(target['expr'], [{'labels': '{}', 'value': -1}] if panel['title'] == 'SNMP collection' else [])
                          for panel in dashboard['panels'] for target in panel['targets']]},
    {'name': 'failed scrape hides old successful device metrics', 'interval': '1m',
     'input_series': [sample('up', '1 0'), sample('systemCPU_Usage', '25 _')],
     'promql_expr_test': [check(panels['CPU usage'])]},
    {'name': 'stopped collector does not show old values or collecting status', 'interval': '1m',
     'input_series': [sample('up', '1 _ _ _'), sample('systemCPU_Usage', '25 _ _ _')],
     'promql_expr_test': [check(panels['CPU usage'], at='3m'),
                          check(panels['SNMP collection'], [{'labels': '{}', 'value': -1}], at='3m')]},
    {'name': 'successful scrape cannot revive stale individual metrics', 'interval': '1m',
     'input_series': [sample('up', '1 1 1 1'), sample('systemCPU_Usage', '25 _ _ _')],
     'promql_expr_test': [check(panels['CPU usage'], at='3m')]},
    {'name': 'zero total memory is unavailable rather than infinite', 'interval': '1m',
     'input_series': [sample('up', '1 1'), sample('systemTotalMem', '0 0'), sample('systemAvailableMem', '0 0')],
     'promql_expr_test': [check(panels['Memory in use'])]},
    {'name': 'pool arithmetic uses bytes and retains pool identity', 'interval': '1m',
     'input_series': [sample('up', '1 1'),
                      sample('storagepoolCapacity', '1000 1000', 'pool_id="1",storagepoolIndex="1"'),
                      sample('storagepoolFreeSize', '250 250', 'pool_id="1",storagepoolIndex="1"')],
     'promql_expr_test': [check(panels['Pool used capacity'], [
         {'labels': '{job="qnap",instance="qnap-01",pool_id="1",storagepoolIndex="1"}', 'value': 750}]),
         check(panels['Pool usage'], [
         {'labels': '{job="qnap",instance="qnap-01",pool_id="1",storagepoolIndex="1"}', 'value': 75}])]},
    {'name': 'zero available memory means fully used', 'interval': '1m',
     'input_series': [sample('up', '1 1'), sample('systemTotalMem', '1000 1000'), sample('systemAvailableMem', '0 0')],
     'promql_expr_test': [check(panels['Memory in use'], [
         {'labels': '{job="qnap",instance="qnap-01"}', 'value': 100}])]},
]

memory = qnap.memory_targets()
processor = qnap.cpu_targets()[1]['expr']
tests += [
    {'name': 'logical processors retain independent percentages including idle CPUs', 'interval': '1m',
     'input_series': [sample('up', '1 1'),
                      sample('hrProcessorLoad', '0 0', 'hrDeviceIndex="196608"'),
                      sample('hrProcessorLoad', '95 95', 'hrDeviceIndex="196609"')],
     'promql_expr_test': [check(processor, [
         {'labels': 'hrProcessorLoad{job="qnap",instance="qnap-01",hrDeviceIndex="196608"}', 'value': 0},
         {'labels': 'hrProcessorLoad{job="qnap",instance="qnap-01",hrDeviceIndex="196609"}', 'value': 95}])]},
    {'name': 'processor samples are hidden after failed scrape', 'interval': '1m',
     'input_series': [sample('up', '1 0'), sample('hrProcessorLoad', '95 95', 'hrDeviceIndex="196608"')],
     'promql_expr_test': [check(processor)]},
    {'name': 'stale processor samples are not revived by a healthy scrape', 'interval': '1m',
     'input_series': [sample('up', '1 1 1 1'), sample('hrProcessorLoad', '95 _ _ _', 'hrDeviceIndex="196608"')],
     'promql_expr_test': [check(processor, at='3m')]},
]
memory_values = {'systemUsedMemory': 300, 'systemAvailableMem': 700,
                 'systemFreeMem': 110, 'systemCacheMemory': 12, 'systemBufferMemory': 0.6}
memory_base = [sample('systemTotalMem', '1000 1000')] + [sample(name, f'{value} {value}') for name, value in memory_values.items()]
tests += [
    {'name': 'memory ratios preserve overlapping counters and small buffer values', 'interval': '1m',
     'input_series': [sample('up', '1 1')] + memory_base,
     'promql_expr_test': [check(target['expr'], [{'labels': '{job="qnap",instance="qnap-01"}', 'value': value / 10}])
                          for target, value in zip(memory, memory_values.values())]},
    {'name': 'memory breakdown disappears when SNMP fails', 'interval': '1m',
     'input_series': [sample('up', '1 0')] + memory_base,
     'promql_expr_test': [check(target['expr']) for target in memory]},
    {'name': 'missing cache does not become zero', 'interval': '1m',
     'input_series': [sample('up', '1 1'), sample('systemTotalMem', '1000 1000')],
     'promql_expr_test': [check(memory[3]['expr'])]},
    {'name': 'zero total hides all memory ratios', 'interval': '1m',
     'input_series': [sample('up', '1 1'), sample('systemTotalMem', '0 0')] +
                     [sample(name, '0 0') for name in memory_values],
     'promql_expr_test': [check(target['expr']) for target in memory]},
    {'name': 'fresh scrape cannot revive stale cache counter', 'interval': '1m',
     'input_series': [sample('up', '1 1 1 1'), sample('systemTotalMem', '1000 1000 1000 1000'),
                      sample('systemCacheMemory', '12 _ _ _')],
     'promql_expr_test': [check(memory[3]['expr'], at='3m')]},
]

for title, metric in [('Network receive', 'ifHCInOctets'), ('Network transmit', 'ifHCOutOctets')]:
    labels = 'ifIndex="4",ifName="eth2"'
    expected_labels = '{job="qnap",instance="qnap-01",ifIndex="4",ifName="eth2"}'
    for name, values, expected in [('byte counters become bits per second', '0+6000x5', 800),
                                   ('idle interfaces remain zero', '0+0x5', 0),
                                   ('counter resets do not produce negative traffic', '0 6000 12000 0 6000 12000', 600)]:
        tests.append({'name': title + ': ' + name, 'interval': '1m',
                      'input_series': [sample('up', '1+0x5'), sample(metric, values, labels)],
                      'promql_expr_test': [check(panels[title], [{'labels': expected_labels, 'value': expected}], at='5m')]})
    for name, health, values in [('failed collection hides rates', '1 1 1 1 1 0', '0+6000x5'),
                                  ('stale counters hide rates despite fresh up', '1+0x5', '0 6000 12000 _ _ _'),
                                  ('single sample cannot produce a rate', '1+0x5', '_ _ _ _ _ 6000')]:
        tests.append({'name': title + ': ' + name, 'interval': '1m',
                      'input_series': [sample('up', health), sample(metric, values, labels)],
                      'promql_expr_test': [check(panels[title], at='5m')]})
    tests.append({'name': title + ': include bonds and VLANs but exclude loopback and virtual bridges',
                  'interval': '1m',
                  'input_series': [sample('up', '1+0x5')] +
                                  [sample(metric, '0+6000x5', f'ifIndex="{index}",ifName="{name}"')
                                   for index, name in [(1, 'lo'), (6, 'bond0'), (12, 'bond0.6'), (13, 'docker0')]],
                  'promql_expr_test': [check(panels[title], [
                      {'labels': '{job="qnap",instance="qnap-01",ifIndex="6",ifName="bond0"}', 'value': 800},
                      {'labels': '{job="qnap",instance="qnap-01",ifIndex="12",ifName="bond0.6"}', 'value': 800}], at='5m')]})

with tempfile.TemporaryDirectory(prefix='qnap-promql-') as directory:
    path = Path(directory) / 'tests.yml'
    path.write_text(yaml.safe_dump({'rule_files': [], 'evaluation_interval': '1m', 'tests': tests}))
    subprocess.run([os.environ.get('PROMTOOL', 'promtool'), 'test', 'rules', str(path)], check=True)
print(f'Validated {len(dashboard["panels"])} panels and {len(tests)} telemetry scenarios.')
