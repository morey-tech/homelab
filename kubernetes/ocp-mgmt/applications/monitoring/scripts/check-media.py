#!/usr/bin/env python3
"""Read-only checks of media dashboard queries, locally or after GitOps deployment."""
import argparse
import base64
import json
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
    parser.add_argument('--local', action='store_true', help='Query local JSON without requiring dashboard deployment')
    parser.add_argument('--skip-tautulli', action='store_true', help='Defer undeployed stream queries (requires --local)')
    args = parser.parse_args()
    if args.skip_tautulli and not args.local:
        parser.error('--skip-tautulli requires --local')
    secret = json.loads(subprocess.check_output([
        'oc', '--context=logged-user', '--request-timeout=15s', '-n', 'monitoring',
        'get', 'secret', 'grafana-admin', '-o', 'json']))
    auth = 'Basic ' + base64.b64encode(b'admin:' + base64.b64decode(secret['data']['password'])).decode()

    def request(path, payload=None):
        req = urllib.request.Request(BASE + path, headers={'Authorization': auth, 'Content-Type': 'application/json'},
                                     data=None if payload is None else json.dumps(payload).encode())
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)

    expected = json.loads((ROOT / 'dashboards/media.json').read_text())
    if args.local:
        dashboard = expected
    else:
        result = request('/api/dashboards/uid/media-services')
        assert result['meta']['provisioned'], 'Dashboard is not provisioned'
        dashboard = result['dashboard']
        assert dashboard['panels'] == expected['panels'], 'Deployed panels differ from local JSON'
    assert request('/api/datasources/uid/ocp-home/health')['status'] == 'OK'
    now = int(time.time() * 1000)
    for panel in dashboard['panels']:
        if panel['datasource']['uid'] == 'infrastructure' and args.skip_tautulli:
            print(f"{panel['title']}: deferred until GitOps deployment")
            continue
        for target in panel['targets']:
            uid = target['datasource']['uid']
            assert uid in ('ocp-home', 'infrastructure')
            query = urllib.parse.urlencode({'query': target['expr']})
            result = request(f'/api/datasources/proxy/uid/{uid}/api/v1/query?' + query)
            assert result['status'] == 'success' and result['data']['result'], f"No current telemetry: {panel['title']}"
        result = request('/api/ds/query', {'from': str(now - 21600000), 'to': str(now),
                         'queries': [dict(t, intervalMs=30000, maxDataPoints=720) for t in panel['targets']]})
        for target in panel['targets']:
            data = result['results'][target['refId']]
            assert not data.get('error') and data.get('status', 200) == 200, panel['title']
            assert any(any(v is not None for v in values)
                       for frame in data.get('frames', [])
                       for field, values in zip(frame['schema']['fields'], frame['data']['values'])
                       if field['type'] == 'number'), f"Empty history: {panel['title']}"
        print(f"{panel['title']}: current telemetry and six-hour Grafana queries passed", flush=True)
    print('Read-only query checks passed. Visual verification remains necessary after GitOps deployment.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Grafana/API check failed: HTTP {error.code} at {error.url}') from None
