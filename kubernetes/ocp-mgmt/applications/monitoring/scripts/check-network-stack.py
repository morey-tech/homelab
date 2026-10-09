#!/usr/bin/env python3
"""Read-only Grafana checks; --local validates queries before GitOps deployment."""
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

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://grafana.apps.ocp-mgmt.rh-lab.morey.tech'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true', help='Query local panels without requiring deployment')
    args = parser.parse_args()
    password = os.environ.get('GRAFANA_PASSWORD')
    if not password:
        secret = json.loads(subprocess.check_output([
            'oc', '--context=logged-user', '--request-timeout=15s', 'get', 'secret',
            'grafana-admin', '-n', 'monitoring', '-o', 'json'], text=True))
        password = base64.b64decode(secret['data']['password']).decode()
    auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()

    def request(path, payload=None):
        req = urllib.request.Request(BASE + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization': auth, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)

    dashboard = json.loads((ROOT / 'dashboards/network-stack.json').read_text())
    if not args.local:
        deployed = request('/api/dashboards/uid/network-stack')
        assert deployed['meta']['provisioned']
        assert deployed['dashboard']['panels'] == dashboard['panels'], 'Deployed panels differ from local JSON'
    assert request('/api/datasources/uid/infrastructure/health')['status'] == 'OK'
    now = int(time.time() * 1000)
    devices = [('pfsense', 'pfsense'), ('mikrotik', 'crs317-b'),
               ('mikrotik', 'crs317-a'), ('unifi', 'usw-enterprise-48-poe')]
    for index, panel in enumerate(dashboard['panels']):
        job, instance = devices[index // 2]
        for target in panel['targets']:
            query = urllib.parse.urlencode({'query': target['expr']})
            result = request('/api/datasources/proxy/uid/infrastructure/api/v1/query?' + query)
            assert result['status'] == 'success', panel['title']
            series = result['data']['result']
            assert series, panel['title'] + ': missing telemetry'
            assert all(s['metric'].get('job') == job and s['metric'].get('instance') == instance
                       and s['metric'].get('interface') for s in series), panel['title']
            result = request('/api/ds/query', {'from': str(now - 21600000), 'to': str(now),
                'queries': [dict(target, intervalMs=60000, maxDataPoints=360)]})['results'][target['refId']]
            assert not result.get('error') and result.get('status', 200) == 200, panel['title']
            assert any(any(v is not None for v in values)
                       for frame in result.get('frames', [])
                       for field, values in zip(frame['schema']['fields'], frame['data']['values'])
                       if field['type'] == 'number'), panel['title'] + ': empty graph'
            print(f'{panel["title"]}: {len(series)} current interfaces; Grafana range query passed')
    print('Local queries verified; provisioning deferred.' if args.local else 'Provisioned dashboard and queries verified.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
