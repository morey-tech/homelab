#!/usr/bin/env python3
"""Read-only verification after the approved changes deploy through GitOps."""
import argparse
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://grafana.apps.ocp-mgmt.rh-lab.morey.tech'
CLUSTERS = {
    'ocp-mgmt': {'url': 'https://thanos-querier.openshift-monitoring.svc:9091',
                 'nodes': {'ms-02', 'ms-03', 'ms-04', 'tr-gpu'}, 'private_ca': True},
    'ocp-home': {'url': 'https://thanos-querier-openshift-monitoring.apps.ocp-home.rh-lab.morey.tech',
                 'nodes': {'ocp-home-01.rh-lab.morey.tech'}, 'private_ca': False},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cluster', choices=[*CLUSTERS, 'all'], default='all')
    args = parser.parse_args()
    selected = CLUSTERS if args.cluster == 'all' else [args.cluster]
    password = os.environ.get('GRAFANA_PASSWORD')
    if not password:
        secret = json.loads(subprocess.check_output([
            'oc', '--context=logged-user', '--request-timeout=15s', 'get', 'secret', 'grafana-admin',
            '-n', 'monitoring', '-o', 'json',
        ], text=True))
        password = base64.b64decode(secret['data']['password']).decode()
    auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(BASE + path, data=data, headers={'Authorization': auth, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=70) as response:
            return json.load(response)

    assert request('/api/health')['database'] == 'ok', 'Grafana database is unhealthy'
    for cluster in selected:
        config = CLUSTERS[cluster]
        datasource = request(f'/api/datasources/uid/{cluster}')
        assert datasource['url'] == config['url']
        assert datasource['readOnly'], 'Data source is not provisioned'
        assert datasource['jsonData']['httpMethod'] == 'GET'
        assert not datasource['jsonData'].get('tlsSkipVerify', False)
        assert datasource['secureJsonFields']['httpHeaderValue1']
        if config['private_ca']:
            assert datasource['secureJsonFields']['tlsCACert']
        health = request(f'/api/datasources/uid/{cluster}/health')
        assert health['status'] == 'OK', health.get('message', 'Data source health failed')
        print(f'{cluster}: authenticated, TLS-verified Thanos data source healthy')
        dashboard = request(f'/api/dashboards/uid/{cluster}-overview')
        assert dashboard['meta']['provisioned'], 'Dashboard is not provisioned'
        for panel in dashboard['dashboard']['panels']:
            query = urllib.parse.urlencode({'query': panel['targets'][0]['expr']})
            result = request(f'/api/datasources/proxy/uid/{cluster}/api/v1/query?' + query)
            assert result['status'] == 'success', panel['title']
            series = result['data']['result']
            print(f"{panel['title']}: {len(series)} series; values: " + ', '.join(s['value'][1] for s in series))
            if panel['title'] in ('Node CPU usage', 'Node memory usage'):
                assert {s['metric']['instance'] for s in series} == config['nodes'], 'Missing node telemetry'
            if panel['title'] == 'Cluster health':
                assert series and series[0]['value'][1] != '-1', 'Core monitoring data is unknown'
            if panel['title'].startswith('GPU '):
                assert series, 'GPU telemetry is missing'
        now = int(time.time() * 1000)
        for panel in dashboard['dashboard']['panels']:
            target = dict(panel['targets'][0], intervalMs=30000, maxDataPoints=720)
            result = request('/api/ds/query', {'from': str(now - 21600000), 'to': str(now), 'queries': [target]})['results']['A']
            assert not result.get('error'), (panel['title'], result.get('error'))
            assert result.get('status', 200) == 200, panel['title']
        print(f'{cluster}: all panel plugin queries passed')
    print('Provisioned dashboard and all query paths verified. Inspect the dashboard visually before relying on the display.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
