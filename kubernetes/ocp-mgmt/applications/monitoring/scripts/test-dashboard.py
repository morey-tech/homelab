#!/usr/bin/env python3
"""Exercise dashboard status semantics with synthetic series using promtool."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('dashboard', ROOT / 'scripts/build-dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
dashboard = module.build()
assert json.loads((ROOT / 'dashboards/ocp-mgmt.json').read_text()) == dashboard, 'Regenerate dashboard JSON'
health = next(p for p in dashboard['panels'] if p['title'] == 'Cluster health')['targets'][0]['expr']
ready = next(p for p in dashboard['panels'] if p['title'] == 'Ready nodes / 4')['targets'][0]['expr']
critical = next(p for p in dashboard['panels'] if p['title'] == 'Critical alerts')['targets'][0]['expr']

base = {
    'up{job="kube-state-metrics",endpoint="https-main"}': 1,
    'up{job="cluster-version-operator"}': 1,
    'up{job="prometheus-k8s"}': 1,
    'ALERTS{alertname="Watchdog",alertstate="firing",severity="none"}': 1,
    'cluster_operator_conditions{name="authentication",condition="Available"}': 1,
    'cluster_operator_conditions{name="authentication",condition="Degraded"}': 0,
    'cluster_operator_conditions{name="authentication",condition="Progressing"}': 0,
    'cluster_operator_conditions{name="version",condition="Available"}': 1,
    'cluster_operator_conditions{name="version",condition="Failing"}': 0,
}
for node in module.NODES:
    base[f'kube_node_status_condition{{condition="Ready",status="true",node="{node}"}}'] = 1

cases = []

def case(name, expected, updates=None, remove=(), expected_ready=4, expected_critical=0, stale=False):
    series = {key: value for key, value in base.items() if not any(s in key for s in remove)}
    series.update(updates or {})
    def result(expr, value):
        return {'expr': expr, 'eval_time': '4m', 'exp_samples': [] if value is None else [{'labels': '{}', 'value': value}]}
    cases.append({'name': name, 'interval': '1m',
                  'input_series': [{'series': key, 'values': f'{value} _x4' if stale else f'{value}x4'} for key, value in series.items()],
                  'promql_expr_test': [result(health, expected), result(ready, expected_ready), result(critical, expected_critical)]})

case('healthy cluster with no warning or critical alerts', 0)
case('warning requires attention', 1, {'ALERTS{alertname="TestWarning",alertstate="firing",severity="warning"}': 1})
case('critical overrides attention', 2, {'ALERTS{alertname="TestWarning",alertstate="firing",severity="warning"}': 1,
                                       'ALERTS{alertname="TestCritical",alertstate="firing",severity="critical"}': 1}, expected_critical=1)
case('node NotReady is unhealthy', 2, {'kube_node_status_condition{condition="Ready",status="true",node="tr-gpu"}': 0}, expected_ready=3)
case('deleted node is unhealthy', 2, remove=('node="tr-gpu"',), expected_ready=3)
case('all nodes missing with a working exporter is unhealthy', 2, remove=('kube_node_status_condition',), expected_ready=0)
case('operator unavailable is unhealthy', 2, {'cluster_operator_conditions{name="authentication",condition="Available"}': 0})
case('operator degraded is unhealthy', 2, {'cluster_operator_conditions{name="authentication",condition="Degraded"}': 1})
case('version operator failing is unhealthy', 2, {'cluster_operator_conditions{name="version",condition="Failing"}': 1})
case('operator progressing requires attention', 1, {'cluster_operator_conditions{name="authentication",condition="Progressing"}': 1})
case('missing Watchdog cannot produce zero critical alerts', -1, remove=('Watchdog',), expected_critical=None)
case('operator data absent is unknown', -1, remove=('cluster_operator_conditions',), expected_critical=None)
case('main KSM endpoint down while self endpoint is up is unknown', -1,
     {'up{job="kube-state-metrics",endpoint="https-main"}': 0, 'up{job="kube-state-metrics",endpoint="https-self"}': 1},
     expected_ready=None, expected_critical=None)
case('CVO down with cached operator data is unknown', -1, {'up{job="cluster-version-operator"}': 0}, expected_critical=None)
case('Prometheus self scrape down is unknown', -1, {'up{job="prometheus-k8s"}': 0}, expected_critical=None)
case('completely absent metrics is unknown', -1, remove=('',), expected_ready=None, expected_critical=None)
case('stale samples in the lookback window is unknown', -1, stale=True, expected_ready=None, expected_critical=None)

promtool = shutil.which('promtool')
if not promtool:
    raise SystemExit('Install promtool or add its directory to PATH')
with tempfile.TemporaryDirectory(prefix='monitoring-promql-') as directory:
    path = Path(directory) / 'tests.yaml'
    path.write_text(yaml.safe_dump({'rule_files': [], 'evaluation_interval': '1m', 'tests': cases}, sort_keys=False))
    subprocess.run([promtool, 'test', 'rules', str(path)], check=True)
print(f'{len(cases)} dashboard health scenarios passed; generated JSON matches its source.')
