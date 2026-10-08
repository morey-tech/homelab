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
EXPECTED = {
    'qnap-01': {'pools': {'1', '2'}, 'shares': {'storage-media', 'storage-mass', 'storage-nvme'}},
    'qnap-02': {'pools': {'1'}, 'shares': {'storage-media', 'storage-mass', 'Container'}},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nas', choices=sorted(EXPECTED), help='Check one NAS; defaults to both')
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
    dashboard = request('/api/dashboards/uid/qnap-overview')
    assert dashboard['meta']['provisioned'], 'QNAP dashboard is not provisioned'
    variable = next(v for v in dashboard['dashboard']['templating']['list'] if v['name'] == 'nas')
    assert not variable['multi'] and not variable['includeAll'], 'NAS selection must isolate one device'
    now = int(time.time() * 1000)
    for nas in ([args.nas] if args.nas else EXPECTED):
        for panel in dashboard['dashboard']['panels']:
            for target in panel['targets']:
                assert 'instance="$nas"' in target['expr'], 'Panel is not parameterized by NAS'
                target = dict(target, expr=target['expr'].replace('$nas', nas))
                query = urllib.parse.urlencode({'query': target['expr']})
                result = request('/api/datasources/proxy/uid/infrastructure/api/v1/query?' + query)
                assert result['status'] == 'success', panel['title']
                series = result['data']['result']
                assert series, nas + ' / ' + panel['title'] + ': missing telemetry'
                assert all(s['metric'].get('instance') == nas for s in series), 'Query returned another NAS or missing telemetry'
                if panel['title'] == 'SNMP collection':
                    assert len(series) == 1 and series[0]['value'][1] == '1', 'SNMP collection failed or is stale'
                if panel['title'] == 'Pool state':
                    assert {s['metric']['pool_id'] for s in series} == EXPECTED[nas]['pools'], 'Missing expected pool'
                if panel['title'] == 'Shared-folder status':
                    assert EXPECTED[nas]['shares'] <= {s['metric']['share'] for s in series}, 'Missing expected share'
                target = dict(target, intervalMs=60000, maxDataPoints=360)
                result = request('/api/ds/query', {'from': str(now - 21600000), 'to': str(now), 'queries': [target]})['results'][target['refId']]
                assert not result.get('error'), (panel['title'], result.get('error'))
                assert result.get('status', 200) == 200, panel['title']
                print(f"{nas} / {panel['title']} / {target['refId']}: {len(series)} current series; Grafana plugin query passed")
    print('QNAP data source, provisioned dashboard, and all query paths verified. Review NAS health values and the dashboard visually.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
