#!/usr/bin/env python3
"""Exercise loss semantics, missing telemetry, restarts and report boundaries."""
import importlib.util
import csv
from datetime import date
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dashboard = load('build-internet-dashboard').build()
assert json.loads((ROOT / 'dashboards/internet.json').read_text()) == dashboard
BASE = 'job="internet_ping",instance="ocp-mgmt"'
TARGET = ',target="cloudflare",scope="internet",host="1.1.1.1",ip="1.1.1.1",source="",tos="0"'


def sample(metric, values, target=True, extra=''):
    return {'series': metric + '{' + BASE + (TARGET if target else '') + extra + '}', 'values': values}


def series(received='0+15x20', **changes):
    values = {'smokeping_requests_total': '0+15x20',
              'smokeping_response_duration_seconds_count': received,
              'smokeping_send_errors_total': '0+0x20',
              'smokeping_receive_errors_total': '0+0x20', 'up': '1+0x20'}
    values.update(changes)
    return [sample(k, v, k not in ['up', 'smokeping_receive_errors_total']) for k, v in values.items() if v is not None]


def check(metric, value=None):
    return {'expr': metric, 'eval_time': '5m', 'exp_samples': [] if value is None else [
        {'labels': metric + '{target="cloudflare",scope="internet"}', 'value': value}]}


LOSS = 'internet:ping_loss:ratio1m'
tests = []


def case(name, data, checks):
    tests.append({'name': name, 'interval': '15s', 'input_series': data, 'promql_expr_test': checks})


case('healthy', series(), [check(LOSS, 0), check('internet:ping_loss:ratio5m', 0)])
case('70 percent loss', series('0+4.5x20'), [check(LOSS, 0.7), check('internet:ping_loss:ratio5m', 0.7)])
case('no replies still records 100 percent loss', series('0+0x20'), [check(LOSS, 1)])
case('late replies cannot create negative loss', series('0+16x20'), [check(LOSS, 0)])
case('missing telemetry stays absent', [], [check(LOSS)])
case('failed scrape is unknown', series(up='1+0x19 0'), [check(LOSS)])
case('old scrape is unknown', series(up='1+0x17 _ _ _'), [check(LOSS)])
case('partial window is unknown', series(smokeping_requests_total='0+15x18 _ 300'), [check(LOSS)])
case('no sending is unknown', series(smokeping_requests_total='0+0x20'), [check(LOSS)])
case('local send errors are unknown', series(smokeping_send_errors_total='0+1x20'), [check(LOSS)])
case('local receive errors are unknown', series(smokeping_receive_errors_total='0+1x20'), [check(LOSS)])
case('missing replies metric is unknown', series(smokeping_response_duration_seconds_count=None), [check(LOSS)])
case('prober restart makes a gap', series(smokeping_requests_total='0+15x18 0 15',
     smokeping_response_duration_seconds_count='0+15x18 0 15'), [check(LOSS)])
case('restart recovers after a complete minute', series(smokeping_requests_total='0+15x10 0+15x9',
     smokeping_response_duration_seconds_count='0+15x10 0+15x9'), [check(LOSS, 0)])
case('five-minute loss requires complete coverage', series(up='1+0x10 0 1+0x8'),
     [check(LOSS, 0), check('internet:ping_loss:ratio5m')])
case('latency histogram quantiles', series() + [
    sample('smokeping_response_duration_seconds_bucket', '0+15x20', extra=',le="0.1"'),
    sample('smokeping_response_duration_seconds_bucket', '0+15x20', extra=',le="+Inf"')],
    [check('internet:ping_rtt_seconds:p50_5m', 0.05), check('internet:ping_rtt_seconds:p95_5m', 0.095)])
case('no replies has no latency', series('0+0x20') + [
    sample('smokeping_response_duration_seconds_bucket', '0+0x20', extra=',le="0.1"'),
    sample('smokeping_response_duration_seconds_bucket', '0+0x20', extra=',le="+Inf"')],
    [check('internet:ping_rtt_seconds:p50_5m'), check('internet:ping_rtt_seconds:p95_5m')])
other = [{**item, 'series': item['series'].replace('target="cloudflare"', 'target="google"')}
         for item in series() if 'target=' in item['series']]
case('loss stays separate across targets', series('0+4.5x20') + other, [
    {'expr': LOSS, 'eval_time': '5m', 'exp_samples': [
        {'labels': LOSS + '{target="cloudflare",scope="internet"}', 'value': 0.7},
        {'labels': LOSS + '{target="google",scope="internet"}', 'value': 0}]}])
wan = next(p for p in dashboard['panels'] if p['title'] == 'WAN upload')['targets'][0]['expr']
case('WAN upload only selects ix2 and converts to bits', [
    {'series': 'up{job="pfsense",instance="pfsense"}', 'values': '1+0x20'},
    {'series': 'ifHCOutOctets{job="pfsense",instance="pfsense",ifIndex="7",ifName="ix2"}', 'values': '0+1500x20'},
    {'series': 'ifHCOutOctets{job="pfsense",instance="pfsense",ifIndex="5",ifName="ix0"}', 'values': '0+3000x20'},
], [{'expr': wan, 'eval_time': '5m', 'exp_samples': [
    {'labels': '{job="pfsense",instance="pfsense",ifIndex="7",ifName="ix2",interface="WAN · ix2"}', 'value': 800}]}])
for success, up, expected, name in [('1+0x20', '1+0x20', 1, 'working service'),
                                  ('0+0x20', '1+0x20', 0, 'failed service'),
                                  ('0+0x20', '0+0x20', None, 'failed service scrape')]:
    metric = 'internet:service_success:ratio1m'
    labels = 'job="internet_services",instance="1.1.1.1:53",target="cloudflare-dns",kind="dns"'
    expected_samples = [] if expected is None else [{'labels': metric + '{target="cloudflare-dns",kind="dns"}', 'value': expected}]
    case(name, [{'series': 'probe_success{' + labels + '}', 'values': success},
                {'series': 'up{' + labels + '}', 'values': up}],
         [{'expr': metric, 'eval_time': '5m', 'exp_samples': expected_samples}])
case('all dashboard expressions parse without filling gaps', [], [
    {'expr': t['expr'], 'eval_time': '5m', 'exp_samples': []}
    for panel in dashboard['panels'] for t in panel['targets']])

with tempfile.TemporaryDirectory(prefix='internet-tests-') as directory:
    path = Path(directory) / 'tests.yml'
    path.write_text(yaml.safe_dump({'rule_files': [str(ROOT / 'internet/rules.yml')],
                                  'evaluation_interval': '1m', 'fuzzy_compare': True, 'tests': tests}))
    subprocess.run([os.environ.get('PROMTOOL', 'promtool'), 'test', 'rules', str(path)], check=True)

# Check generated wiring and that no new privilege is introduced.
deployment = yaml.safe_load((ROOT / 'smokeping-prober.yaml').read_text())['spec']['template']
assert deployment['metadata']['annotations']['openshift.io/required-scc'] == 'restricted-v2'
assert deployment['spec']['containers'][0]['securityContext']['capabilities'] == {'drop': ['ALL']}
config = yaml.safe_load((ROOT / 'internet/smokeping.yml').read_text())
assert all(t['protocol'] == 'udp' and t['network'] == 'ip4' and t['interval'] == '1s' for t in config['targets'])
kustomization = yaml.safe_load((ROOT / 'kustomization.yaml').read_text())
assert 'smokeping-prober.yaml' in kustomization['resources']
assert any(c['name'] == 'grafana-internet-dashboard' for c in kustomization['configMapGenerator'])

report = load('report-internet')
assert report.PING_TARGETS == {t['labels']['target']: t['labels']['scope'] for t in config['targets']}
assert set(report.SERVICE_TARGETS) == set(re.findall(r'^\s+target\s+= \"([^\"]+)\"', (ROOT / 'config.alloy').read_text(), re.M))
points = [(60, .7), (120, 1), (240, .8), (300, 0), (360, .1)]
assert [len(e) for e in report.episodes(points)] == [2, 1, 1]
row = report.summary(date(2026, 10, 1), 'cloudflare', 'internet', points, True)
assert row['observed_minutes'] == 5 and row['unknown_minutes'] == 1435
assert row['mean_loss_percent'] == 52 and row['minutes_loss_ge_99_percent'] == 1
assert report.summary(date(2026, 10, 1), 'quad9', 'internet', [], True)['mean_loss_percent'] == ''

# Run the complete CSV writer against a stored-sample API response. Do not
# require a live cluster or let a selector's lookback fill missing minutes.
payload = {'status': 'success', 'data': {'resultType': 'matrix', 'result': [
    {'metric': {'__name__': report.LOSS, 'target': 'cloudflare', 'scope': 'internet'},
     'values': [[1790812800 + t, str(v)] for t, v in points]},
]}}
with tempfile.TemporaryDirectory(prefix='internet-report-test-') as directory:
    out = Path(directory) / 'report'
    with patch.object(report, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(payload).encode())), \
         patch.object(sys, 'argv', ['report-internet.py', '--start', '2026-10-01', '--end', '2026-10-02', '--output', str(out)]):
        report.main()
    rows = list(csv.DictReader((out / 'daily.csv').open()))
    assert len(rows) == 8
    assert next(r for r in rows if r['target'] == 'quad9')['unknown_minutes'] == '1440'
    assert len(list(csv.DictReader((out / 'samples.csv').open()))) == 5
    assert len(list(csv.DictReader((out / 'episodes.csv').open()))) == 3
    assert json.loads((out / 'metadata.json').read_text())['complete'] is True
print(f'Internet Quality: {len(tests)} PromQL scenarios, deployment wiring and CSV report checks passed.')
