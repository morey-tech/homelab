#!/usr/bin/env python3
"""Validate media pod accounting and telemetry failures with synthetic Prometheus series."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('media', ROOT / 'scripts/build-media-dashboard.py')
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)
spec = importlib.util.spec_from_file_location('check_media', ROOT / 'scripts/check-media.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def main():
    dashboard = media.build()
    assert dashboard == json.loads((ROOT / 'dashboards/media.json').read_text()), 'Regenerate media JSON'
    rows = [p for p in dashboard['panels'] if p['type'] == 'row']
    assert len(rows) == 1 and rows[0]['collapsed'] is True
    assert len(rows[0]['panels']) == 3 * len(media.SECONDARY)
    assert {p['title'] for p in rows[0]['panels']} == {
        name + suffix for _, name in media.SECONDARY for suffix in (' CPU', ' memory', ' network')}
    panels = list(checker.query_panels(dashboard['panels']))
    assert len(panels) == 40 and len({p['id'] for p in panels}) == 40
    assert rows[0]['id'] not in {p['id'] for p in panels}
    occupied = set()
    for panel in panels:
        g = panel['gridPos']
        cells = {(x, y) for x in range(g['x'], g['x']+g['w']) for y in range(g['y'], g['y']+g['h'])}
        assert not cells & occupied, 'Panels overlap'
        occupied |= cells
        assert panel['datasource']['uid'] == ('infrastructure' if panel['title'] in (
            'Plex stream history', 'Direct Play', 'Direct Stream', 'Transcoding', 'SAB remaining',
            'Plex bandwidth estimates', 'Media share used', 'SAB download speed') else 'ocp-home')
    assert max(p['gridPos']['y'] + p['gridPos']['h'] for p in dashboard['panels'] if p['type'] != 'row') == 19
    assert not any(p['title'] in ('Total', 'WAN est.', 'WAN traffic — pfSense and Plex') for p in panels)
    assert all(0 <= p['gridPos']['x'] < p['gridPos']['x'] + p['gridPos']['w'] <= 24 for p in panels)
    header = rows[0]['gridPos']
    assert not occupied & {(x, header['y']) for x in range(24)}
    assert sum('Shared host network' in p['title'] for p in panels) == 1
    assert not any(p['title'] in ('Plex network', 'SABnzbd network') for p in panels)

    pod = 'sonarr-abcde-12345'
    pod_labels = f'namespace="sonarr",pod="{pod}"'
    cadvisor = f'job="kubelet",instance="node:10250",metrics_path="/metrics/cadvisor",{pod_labels}'
    ksm = f'job="kube-state-metrics",endpoint="https-main",{pod_labels}'
    cpu = media.resource_query('sonarr', 'container_cpu_usage_seconds_total', True)
    memory = media.resource_query('sonarr', 'container_memory_working_set_bytes')
    network = media.network_query('sonarr', 'receive')
    cadvisor_up = 'up{job="kubelet",instance="node:10250",metrics_path="/metrics/cadvisor"}'
    ksm_up = 'up{job="kube-state-metrics",endpoint="https-main"}'
    phase = f'kube_pod_status_phase{{{ksm},phase="Running"}}'
    info = f'kube_pod_info{{{ksm},host_network="false"}}'
    base = {cadvisor_up: '1x6', ksm_up: '1x6', phase: '1x6', info: '1x6'}
    for container, cores, size in [('main', 1, 100), ('sidecar', 0.5, 50), ('POD', 10, 1000), ('', 10, 1000)]:
        labels = cadvisor + f',container="{container}"'
        base[f'container_cpu_usage_seconds_total{{{labels}}}'] = f'0+{cores*60}x6'
        base[f'container_memory_working_set_bytes{{{labels}}}'] = f'{size}x6'
    # Duplicate scrape series must not double application resource usage.
    for metric, values in [('container_cpu_usage_seconds_total', '0+60x6'), ('container_memory_working_set_bytes', '100x6')]:
        base[f'{metric}{{{cadvisor},container="main",replica="other"}}'] = values
    for interface, container, rate in [('eth0', 'POD', 100), ('net1', 'POD', 50), ('lo', 'POD', 1000), ('eth0', 'main', 1000)]:
        base[f'container_network_receive_bytes_total{{{cadvisor},container="{container}",interface="{interface}"}}'] = f'0+{rate*60}x6'
    base[f'container_network_receive_bytes_total{{{cadvisor},container="POD",interface="eth0",replica="other"}}'] = '0+6000x6'

    cases = []

    def case(name, updates=None, remove=(), expected=(1.5, 150, 1200)):
        series = {k: v for k, v in base.items() if not any(s in k for s in remove)}
        series.update(updates or {})
        cases.append({'name': name, 'interval': '1m',
                      'input_series': [{'series': k, 'values': v} for k, v in series.items()],
                      'promql_expr_test': [{'expr': expr, 'eval_time': '6m', 'exp_samples': [] if value is None else [
                          {'labels': '{'+pod_labels+'}', 'value': value}]} for expr, value in zip((cpu, memory, network), expected)]})

    case('sum application containers; deduplicate scrapes; sandbox network; exclude loopback; convert bytes to bits')
    case('failed pod is excluded', {phase: '0x6'}, expected=(None, None, None))
    case('failed cAdvisor scrape cannot display cached data', {cadvisor_up: '0x6'}, expected=(None, None, None))
    case('failed KSM scrape cannot confirm running pods', {ksm_up: '0x6'}, expected=(None, None, None))
    case('missing running phase', remove=('kube_pod_status_phase',), expected=(None, None, None))
    case('stale running phase', {phase: '1x2 _x4'}, expected=(None, None, None))
    case('stale scrape health', {cadvisor_up: '1x2 _x4'}, expected=(None, None, None))
    case('missing network identity', remove=('kube_pod_info',), expected=(1.5, 150, None))
    case('host networking must never be attributed to an app',
         {f'kube_pod_info{{{ksm},host_network="true"}}': '1x6'}, remove=('kube_pod_info',), expected=(1.5, 150, None))
    case('absent app telemetry is not zero', remove=('container_',), expected=(None, None, None))
    case('idle network remains zero', {k: '100x6' for k in base if k.startswith('container_network')}, expected=(1.5, 150, 0))
    case('stale counters in range window cannot imply activity',
         {k: '0+60x2 _x4' for k in base if k.startswith('container_')}, expected=(None, None, None))
    case('CPU counter reset handled before aggregation',
         # The range includes minutes 2..6: 180 seconds of corrected increase
         # over 240 seconds per container, or 0.75 cores each.
         {k: '0 60 120 180 0 60 120' for k in base if k.startswith('container_cpu')}, expected=(1.5, 150, 1200))
    case('wrong namespace cannot supply app telemetry',
         {k.replace('namespace="sonarr"', 'namespace="radarr"'): v for k, v in base.items() if k.startswith('container_')},
         remove=('container_',), expected=(None, None, None))

    # A current stat must not reuse a historical non-null value after a failure.
    for stat in (p for p in panels if p['type'] in ('stat', 'gauge')):
        assert stat['targets'][0]['instant'] and not stat['targets'][0]['range']
    stream_metric = 'tautulli_streams{job="tautulli",instance="plex"}'
    stream_up = 'up{job="tautulli",instance="plex"}'
    for name, values, up_values, expected in [
        ('active sessions', '3x6', '1x6', 3), ('no sessions', '0x6', '1x6', 0),
        ('scrape failure', '3x6', '0x6', None), ('stale metric', '3x2 _x4', '1x6', None),
        ('stale health', '3x6', '1x2 _x4', None), ('missing metric', '_x7', '1x6', None),
        ('non-numeric response', 'NaN NaN NaN NaN NaN NaN NaN', '1x6', None), ('invalid negative count', '-1x6', '1x6', None)]:
        cases.append({'name': 'Tautulli '+name, 'interval': '1m',
                      'input_series': [{'series': stream_metric, 'values': values}, {'series': stream_up, 'values': up_values}],
                      'promql_expr_test': [{'expr': media.stream_query(), 'eval_time': '6m',
                          'exp_samples': [] if expected is None else [{'labels': stream_metric, 'value': expected}]}]})

    wan_metric = 'tautulli_wan_bandwidth_kilobits_per_second{job="tautulli",instance="plex"}'
    for name, values, up_values, expected in [
        ('kbps to Mbps', '31253x6', '1x6', 31.253), ('zero WAN demand', '0x6', '1x6', 0),
        ('failed scrape', '31253x6', '0x6', None), ('missing value', '_x7', '1x6', None),
        ('stale value', '31253x2 _x4', '1x6', None), ('stale health', '31253x6', '1x2 _x4', None),
        ('negative value', '-1x6', '1x6', None), ('invalid value', 'NaN NaN NaN NaN NaN NaN NaN', '1x6', None)]:
        cases.append({'name': 'WAN '+name, 'interval': '1m',
                      'input_series': [{'series': wan_metric, 'values': values}, {'series': stream_up, 'values': up_values}],
                      'promql_expr_test': [{'expr': media.bandwidth_query('wan'), 'eval_time': '6m',
                          'exp_samples': [] if expected is None else [{'labels': '{job="tautulli",instance="plex"}', 'value': expected}]}]})

    cases.append({'name': 'LAN and WAN estimates remain distinct', 'interval': '1m',
                  'input_series': [{'series': stream_up, 'values': '1x6'},
                      {'series': wan_metric, 'values': '1000x6'},
                      {'series': wan_metric.replace('_wan_', '_lan_'), 'values': '2000x6'}],
                  'promql_expr_test': [{'expr': media.bandwidth_query(scope), 'eval_time': '6m',
                      'exp_samples': [{'labels': '{job="tautulli",instance="plex"}', 'value': value}]}
                      for scope, value in [('wan', 1), ('lan', 2)]]})
    for metric, scale, value in [('sabnzbd_download_kibibytes_per_second', 1024, 2048),
                                 ('sabnzbd_queue_remaining_mebibytes', 1048576, 2097152)]:
        labels = '{job="sabnzbd",instance="sabnzbd"}'
        for name, values, health, expected in [
            ('binary units', '2x6', '1x6', value), ('idle', '0x6', '1x6', 0),
            ('failed scrape', '2x6', '0x6', None), ('missing metric', '_x7', '1x6', None),
            ('stale metric', '2x2 _x4', '1x6', None), ('stale health', '2x6', '1x2 _x4', None),
            ('negative', '-1x6', '1x6', None), ('invalid', 'NaN NaN NaN NaN NaN NaN NaN', '1x6', None)]:
            cases.append({'name': metric+' '+name, 'interval': '1m',
                          'input_series': [{'series': metric+labels, 'values': values},
                                           {'series': 'up'+labels, 'values': health}],
                          'promql_expr_test': [{'expr': media.sab_query(metric, scale), 'eval_time': '6m',
                              'exp_samples': [] if expected is None else [{'labels': labels, 'value': expected}]}]})
    labels = 'job="qnap",instance="qnap-01",share="storage-media",sharedFolderIndex="1"'
    for name, total, free, health, expected in [
        ('used ratio', '1000x6', '250x6', '1x6', 75), ('empty share', '1000x6', '1000x6', '1x6', 0),
        ('full share', '1000x6', '0x6', '1x6', 100), ('zero capacity', '0x6', '0x6', '1x6', None),
        ('inconsistent capacity', '1000x6', '1100x6', '1x6', None),
        ('negative free', '1000x6', '-1x6', '1x6', None),
        ('stale capacity', '1000x2 _x4', '250x6', '1x6', None),
        ('missing free', '1000x6', '_x7', '1x6', None),
        ('stale free', '1000x6', '250x2 _x4', '1x6', None),
        ('failed scrape', '1000x6', '250x6', '0x6', None),
        ('stale scrape health', '1000x6', '250x6', '1x2 _x4', None)]:
        series = [{'series': 'sharedFolderCapacity{'+labels+'}', 'values': total},
                  {'series': 'sharedFolderFreeSize{'+labels+'}', 'values': free},
                  {'series': 'up{job="qnap",instance="qnap-01"}', 'values': health}]
        for decoy in [labels.replace('qnap-01', 'qnap-02'), labels.replace('storage-media', 'storage-mass')]:
            series += [{'series': 'sharedFolderCapacity{'+decoy+'}', 'values': '100x6'},
                       {'series': 'sharedFolderFreeSize{'+decoy+'}', 'values': '10x6'}]
        cases.append({'name': 'Media share '+name, 'interval': '1m', 'input_series': series,
                      'promql_expr_test': [{'expr': media.media_share_query(), 'eval_time': '6m',
                          'exp_samples': [] if expected is None else [{'labels': '{'+labels+'}', 'value': expected}]}]})

    promtool = os.environ.get('PROMTOOL') or shutil.which('promtool')
    if not promtool:
        raise SystemExit('Install promtool or set PROMTOOL to its executable path')
    with tempfile.TemporaryDirectory(prefix='media-dashboard-test-') as tmp:
        path = Path(tmp) / 'tests.yaml'
        path.write_text(yaml.safe_dump({'rule_files': [], 'evaluation_interval': '1m', 'tests': cases}))
        subprocess.run([promtool, 'test', 'rules', str(path)], check=True)
    print(f'{len(cases)} synthetic metric cases and dashboard layout passed')


if __name__ == '__main__':
    main()
