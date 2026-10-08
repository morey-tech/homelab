#!/usr/bin/env python3
"""Read-only verification after the pfSense changes deploy through GitOps."""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://grafana.apps.ocp-mgmt.rh-lab.morey.tech'


def main():
    password = os.environ.get('GRAFANA_PASSWORD')
    if not password:
        secret = json.loads(subprocess.check_output([
            'oc', '--context=logged-user', '--request-timeout=15s', 'get', 'secret',
            'grafana-admin', '-n', 'monitoring', '-o', 'json'], text=True))
        password = base64.b64decode(secret['data']['password']).decode()
    auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(BASE + path, data=data,
            headers={'Authorization': auth, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=70) as response:
            return json.load(response)

    source = request('/api/datasources/uid/infrastructure')
    assert source['url'] == 'http://prometheus.monitoring.svc:9090'
    assert source['readOnly'], 'Infrastructure data source is not provisioned'
    assert request('/api/datasources/uid/infrastructure/health')['status'] == 'OK'
    dashboard = request('/api/dashboards/uid/pfsense-overview')
    assert dashboard['meta']['provisioned'], 'pfSense dashboard is not provisioned'
    now = int(time.time() * 1000)
    for panel in dashboard['dashboard']['panels']:
        for target in panel['targets']:
            query = urllib.parse.urlencode({'query': target['expr']})
            result = request('/api/datasources/proxy/uid/infrastructure/api/v1/query?' + query)
            assert result['status'] == 'success', panel['title']
            series = result['data']['result']
            assert series, panel['title'] + ': missing telemetry'
            assert all(s['metric'].get('instance') == 'pfsense' for s in series), 'Unexpected device or unknown telemetry'
            if panel['title'] == 'SNMP collection':
                assert len(series) == 1 and series[0]['value'][1] == '1', 'Collection failed or is stale'
            if panel['title'] in ('Physical interface receive', 'Physical interface transmit'):
                wan = next(s for s in series if s['metric']['ifName'] == 'ix2')
                assert wan['metric']['interface'], 'Missing WAN legend'
            if panel['title'] in ('Logical interface receive', 'Logical interface transmit'):
                assert {'lagg0', 'lagg0.3', 'lagg0.6', 'lagg0.8', 'lagg0.20', 'tun_wg0'} <= {s['metric']['ifName'] for s in series}
            target = dict(target, intervalMs=60000, maxDataPoints=360)
            result = request('/api/ds/query', {'from': str(now - 21600000), 'to': str(now), 'queries': [target]})['results'][target['refId']]
            assert not result.get('error'), (panel['title'], result.get('error'))
            assert result.get('status', 200) == 200, panel['title']
            print(f"{panel['title']} / {target['refId']}: {len(series)} current series; Grafana plugin query passed")
    print('pfSense data source, provisioned dashboard, and all query paths verified. Review the dashboard visually.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
