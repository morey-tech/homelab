#!/usr/bin/env python3
"""Read-only verification after the approved changes deploy through GitOps."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://grafana.apps.ocp-mgmt.rh-lab.morey.tech'
SWITCHES = ['usw-enterprise-48-poe']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--switch', choices=SWITCHES, help='Check one switch; defaults to all')
    args = parser.parse_args()
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
    dashboard = request('/api/dashboards/uid/unifi-overview')
    assert dashboard['meta']['provisioned'], 'UniFi dashboard is not provisioned'
    expected = json.loads((Path(__file__).resolve().parents[1] / 'dashboards/unifi.json').read_text())
    assert dashboard['dashboard']['panels'] == expected['panels'], 'Deployed panels differ from local JSON'
    variable = next(v for v in dashboard['dashboard']['templating']['list'] if v['name'] == 'switch')
    assert not variable['multi'] and not variable['includeAll'], 'switch selection must isolate one device'
    now = int(time.time() * 1000)
    for switch in ([args.switch] if args.switch else SWITCHES):
        for panel in dashboard['dashboard']['panels']:
            for target in panel['targets']:
                assert 'instance="$switch"' in target['expr'], 'Panel is not parameterized by switch'
                target = dict(target, expr=target['expr'].replace('$switch', switch))
                query = urllib.parse.urlencode({'query': target['expr']})
                result = request('/api/datasources/proxy/uid/infrastructure/api/v1/query?' + query)
                assert result['status'] == 'success', panel['title']
                series = result['data']['result']
                assert series, switch + ' / ' + panel['title'] + ': missing telemetry'
                assert all(s['metric'].get('instance') == switch for s in series), 'Query returned another switch or missing telemetry'
                if panel['title'] == 'SNMP collection':
                    assert len(series) == 1 and series[0]['value'][1] == '1', 'SNMP collection failed or is stale'
                if panel['title'] == 'Port link status':
                    expected_ports = {f'0/{i}' for i in range(1, 53)}
                    assert {s['metric']['ifName'] for s in series} == expected_ports, 'Missing expected physical port'
                if panel['title'] in ('LAG receive', 'LAG transmit'):
                    assert len(series) == 26, 'Missing expected aggregation interface'
                target = dict(target, intervalMs=60000, maxDataPoints=360)
                result = request('/api/ds/query', {'from': str(now - 21600000), 'to': str(now), 'queries': [target]})['results'][target['refId']]
                assert not result.get('error'), (panel['title'], result.get('error'))
                assert result.get('status', 200) == 200, panel['title']
                assert any(any(v is not None for v in values)
                           for frame in result.get('frames', [])
                           for field, values in zip(frame['schema']['fields'], frame['data']['values'])
                           if field['type'] == 'number'), (panel['title'], 'Empty Grafana result')
                print(f"{switch} / {panel['title']} / {target['refId']}: {len(series)} current series; Grafana plugin query passed")
    print('UniFi data source, provisioned dashboard, and all query paths verified. Review switch health values and the dashboard visually.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
