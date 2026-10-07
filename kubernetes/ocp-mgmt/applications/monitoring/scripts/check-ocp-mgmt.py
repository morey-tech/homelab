#!/usr/bin/env python3
"""Read-only verification after the approved changes deploy through GitOps."""
import base64
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://grafana.apps.ocp-mgmt.rh-lab.morey.tech'


def main():
    password = os.environ.get('GRAFANA_PASSWORD')
    if not password:
        secret = json.loads(subprocess.check_output([
            'oc', '--request-timeout=15s', 'get', 'secret', 'grafana-admin',
            '-n', 'monitoring', '-o', 'json',
        ], text=True))
        password = base64.b64decode(secret['data']['password']).decode()
    auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()

    def get(path):
        request = urllib.request.Request(BASE + path, headers={'Authorization': auth})
        with urllib.request.urlopen(request, timeout=70) as response:
            return json.load(response)

    assert get('/api/health')['database'] == 'ok', 'Grafana database is unhealthy'
    datasource = get('/api/datasources/uid/ocp-mgmt')
    assert datasource['url'] == 'https://thanos-querier.openshift-monitoring.svc:9091'
    assert datasource['readOnly'], 'Data source is not provisioned'
    assert datasource['jsonData']['httpMethod'] == 'GET'
    assert not datasource['jsonData'].get('tlsSkipVerify', False)
    assert datasource['secureJsonFields']['httpHeaderValue1']
    assert datasource['secureJsonFields']['tlsCACert']
    health = get('/api/datasources/uid/ocp-mgmt/health')
    assert health['status'] == 'OK', health.get('message', 'Data source health failed')
    print('Grafana database and authenticated, TLS-verified Thanos data source: healthy')
    dashboard = get('/api/dashboards/uid/ocp-mgmt-overview')
    assert dashboard['meta']['provisioned'], 'Dashboard is not provisioned'
    for panel in dashboard['dashboard']['panels']:
        query = urllib.parse.urlencode({'query': panel['targets'][0]['expr']})
        result = get('/api/datasources/proxy/uid/ocp-mgmt/api/v1/query?' + query)
        assert result['status'] == 'success', panel['title']
        series = result['data']['result']
        print(f"{panel['title']}: {len(series)} series; values: " + ', '.join(s['value'][1] for s in series))
        if panel['title'] in ('Node CPU usage', 'Node memory usage'):
            assert {s['metric']['instance'] for s in series} == {'ms-02', 'ms-03', 'ms-04', 'tr-gpu'}, 'Missing node telemetry'
        if panel['title'] == 'Cluster health':
            assert series and series[0]['value'][1] != '-1', 'Core monitoring data is unknown'
        if panel['title'].startswith('GPU '):
            assert series, 'GPU telemetry is missing'
    print('Provisioned dashboard and all query paths verified. Inspect the dashboard visually before relying on the display.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
