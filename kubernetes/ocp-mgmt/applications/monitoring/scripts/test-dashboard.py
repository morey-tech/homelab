#!/usr/bin/env python3
"""Exercise dashboard status and network rates with synthetic series using promtool."""
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
def cluster_cases(cluster):
    dashboard = module.build(cluster)
    nodes = module.CLUSTERS[cluster]['nodes']
    node_count = len(nodes)
    missing_node = nodes[-1]
    assert json.loads((ROOT / f'dashboards/{cluster}.json').read_text()) == dashboard, 'Regenerate dashboard JSON'
    health = next(p for p in dashboard['panels'] if p['title'] == 'Cluster health')['targets'][0]['expr']
    ready = next(p for p in dashboard['panels'] if p['title'] == f'Ready nodes / {node_count}')['targets'][0]['expr']
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
    for node in nodes:
        base[f'kube_node_status_condition{{condition="Ready",status="true",node="{node}"}}'] = 1

    cases = []

    def case(name, expected, updates=None, remove=(), expected_ready=node_count, expected_critical=0, stale=False):
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
    case('node NotReady is unhealthy', 2, {f'kube_node_status_condition{{condition="Ready",status="true",node="{missing_node}"}}': 0}, expected_ready=node_count - 1)
    case('deleted node is unhealthy', 2, remove=(f'node="{missing_node}"',), expected_ready=node_count - 1)
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

    # Regex metacharacters in the home node's DNS name must remain literal.
    if cluster == 'ocp-home':
        wrong_node = nodes[0].replace('.', 'x')
        case('similarly named node cannot mask the missing home node', 2,
             {f'kube_node_status_condition{{condition="Ready",status="true",node="{wrong_node}"}}': 1},
             remove=('kube_node_status_condition',), expected_ready=0)
    for p in dashboard['panels']:
        assert p['datasource']['uid'] == cluster
        assert all(t['datasource']['uid'] == cluster for t in p['targets'])
    cases.extend(network_cases(cluster, dashboard))
    return cases


def network_cases(cluster, dashboard):
    node = module.CLUSTERS[cluster]['nodes'][0]
    device = 'bond0' if cluster == 'ocp-home' else 'enp2s0f0'
    labels = f'job="node-exporter",instance="{node}"'
    up = f'up{{{labels}}}'
    results = []
    for direction in ('receive', 'transmit'):
        p = next(p for p in dashboard['panels'] if p['title'] == 'Node network ' + direction)
        assert p['fieldConfig']['defaults']['unit'] == 'bps'
        assert 'max' not in p['fieldConfig']['defaults']
        assert p['targets'][0]['range'] and not p['targets'][0]['instant']
        metric = f'node_network_{direction}_bytes_total'
        counter = f'{metric}{{{labels},device="{device}"}}'
        healthy = {up: '1+0x5', counter: '0+6000x5'}

        def case(name, series, expected):
            results.append({'name': direction + ': ' + name, 'interval': '1m',
                            'input_series': [{'series': key, 'values': value} for key, value in series.items()],
                            'promql_expr_test': [{'expr': p['targets'][0]['expr'], 'eval_time': '5m',
                                'exp_samples': [{'labels': f'{{instance="{node}",device="{dev}"}}', 'value': value}
                                                for dev, value in expected.items()]}]})

        case('convert to bits/s', healthy, {device: 800})
        case('idle remains zero', {**healthy, counter: '0+0x5'}, {device: 0})
        case('counter resets', {**healthy, counter: '0 6000 12000 0 6000 12000'}, {device: 600})
        case('failed scrape', {**healthy, up: '1 1 1 1 1 0'}, {})
        case('stale source', {**healthy, up: '1 1 1 _ _ _'}, {})
        case('stale counter despite healthy exporter', {**healthy, counter: '0 6000 12000 _ _ _'}, {})
        case('absent telemetry', {}, {})
        case('one sample cannot produce a rate', {**healthy, counter: '_ _ _ _ _ 6000'}, {})
        excluded = ['lo', 'ovs-system', 'genev_sys_6081', 'veth123', 'wlp90s0']
        if cluster == 'ocp-home':
            excluded += ['enp2s0f0', 'enp2s0f1']
        case('exclude overlapping and unrelated interfaces', {
            **healthy, **{f'{metric}{{{labels},device="{dev}"}}': '0+600000x5' for dev in excluded}
        }, {device: 800})
        other_node = node.replace('.', 'x') if cluster == 'ocp-home' else 'unmanaged-node'
        case('exclude nodes outside this cluster topology', {
            **healthy, up.replace(node, other_node): '1+0x5',
            counter.replace(node, other_node): '0+600000x5'
        }, {device: 800})
        if cluster == 'ocp-mgmt':
            case('keep interface rates separate', {
                **healthy, f'{metric}{{{labels},device="enp2s0f1"}}': '0+12000x5'
            }, {device: 800, 'enp2s0f1': 1600})
    return results


cases = []
for cluster in module.CLUSTERS:
    for case in cluster_cases(cluster):
        case['name'] = cluster + ': ' + case['name']
        cases.append(case)

promtool = shutil.which('promtool')
if not promtool:
    raise SystemExit('Install promtool or add its directory to PATH')
with tempfile.TemporaryDirectory(prefix='monitoring-promql-') as directory:
    path = Path(directory) / 'tests.yaml'
    path.write_text(yaml.safe_dump({'rule_files': [], 'evaluation_interval': '1m', 'tests': cases}, sort_keys=False))
    subprocess.run([promtool, 'test', 'rules', str(path)], check=True)
print(f'{len(cases)} dashboard health/network scenarios passed; generated JSON matches its source.')
