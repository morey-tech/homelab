#!/usr/bin/env python3
"""Exercise the pinned JSON exporter against a local Tautulli API fixture."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    exporter = os.environ.get('JSON_EXPORTER')
    if not exporter:
        raise SystemExit('Set JSON_EXPORTER to the json_exporter v0.8.0 executable')
    state = {'key': 'test-only-key', 'status': 200, 'body': {}, 'auth': False}

    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            state['auth'] = self.headers.get('X-Api-Key') == state['key']
            self.send_response(state['status'] if state['auth'] else 401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(state['body']).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='tautulli-exporter-test-') as tmp:
            tmp = Path(tmp)
            keyfile = tmp / 'api-key'
            keyfile.write_text(state['key'])
            config = yaml.safe_load((ROOT / 'tautulli/config.yml').read_text())
            config['modules']['activity']['http_client_config']['http_headers']['X-Api-Key']['files'] = [str(keyfile)]
            configfile = tmp / 'config.yml'
            configfile.write_text(yaml.safe_dump(config))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen([exporter, '--config.file='+str(configfile), f'--web.listen-address=127.0.0.1:{port}'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f'http://127.0.0.1:{port}'
            for _ in range(50):
                try:
                    with urlopen(base+'/metrics', timeout=1):
                        break
                except URLError:
                    if process.poll() is not None:
                        raise AssertionError('Exporter rejected configuration')
                    time.sleep(0.1)
            else:
                raise AssertionError('Exporter did not start')
            probe = base+'/probe?'+urlencode({'module': 'activity', 'target': f'http://127.0.0.1:{server.server_port}/api/v2?cmd=get_activity'})

            def scrape():
                try:
                    with urlopen(probe, timeout=5) as response:
                        text = response.read().decode()
                except HTTPError:
                    return {}
                return {line.split()[0]: float(line.split()[1]) for line in text.splitlines() if line.startswith('tautulli_streams')}

            def activity(total, play, direct, transcode):
                state['status'] = 200
                state['body'] = {'response': {'result': 'success', 'data': {
                    'stream_count': total, 'stream_count_direct_play': play,
                    'stream_count_direct_stream': direct, 'stream_count_transcode': transcode}}}

            activity('6', 3, 2, 1)
            assert scrape() == {'tautulli_streams': 6, 'tautulli_streams_direct_play': 3,
                                'tautulli_streams_direct_stream': 2, 'tautulli_streams_transcode': 1}
            assert state['auth'], 'API key header was not sent'
            activity('0', 0, 0, 0)
            assert scrape() == dict.fromkeys(['tautulli_streams', 'tautulli_streams_direct_play',
                                              'tautulli_streams_direct_stream', 'tautulli_streams_transcode'], 0)
            state['body'] = {'response': {'result': 'error', 'data': {}}}
            assert scrape() == {}, 'API errors must not become zero streams'
            state['body'] = {'response': {'result': 'success', 'data': {}}}
            assert scrape() == {}, 'Missing data must not become zero streams'
            activity('6', 3, 2, 1)
            state['status'] = 401
            assert scrape() == {}, 'HTTP failures must not reuse previous metrics'
            state['status'] = 200
            state['key'] = 'rotated-test-only-key'
            keyfile.write_text(state['key'])
            assert scrape()['tautulli_streams'] == 6 and state['auth'], 'Projected key rotation was not read'
            print('Exporter checks passed: API header, counts, zero, API error, missing data, HTTP failure, key rotation')
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
