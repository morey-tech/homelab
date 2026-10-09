#!/usr/bin/env python3
"""Test the pinned JSON exporter with a local SABnzbd queue API fixture."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    exporter = os.environ.get('JSON_EXPORTER')
    if not exporter:
        raise SystemExit('Set JSON_EXPORTER to the json_exporter v0.8.0 executable')
    # Special characters ensure the key is form-encoded, not concatenated raw.
    key = 'fixture-only +&=key'
    state = {'status': 200, 'body': {}, 'authenticated': False, 'redirected': False}

    class Fixture(BaseHTTPRequestHandler):
        def do_POST(self):
            params = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            state['authenticated'] = (params.get('apikey') == [key] and params.get('mode') == ['queue']
                                      and params.get('output') == ['json'] and params.get('limit') == ['1']
                                      and self.path == '/api'
                                      and self.headers.get('Content-Type') == 'application/x-www-form-urlencoded')
            self.send_response(state['status'] if state['authenticated'] else 403)
            if state['status'] == 302:
                self.send_header('Location', '/redirected')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(state['body']).encode())

        def do_GET(self):
            state['redirected'] = True
            self.send_response(500)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env['SABNZBD_API_KEY'] = key
    process = subprocess.Popen([exporter, '--config.file='+str(ROOT/'sabnzbd/config.yml'),
                                f'--web.listen-address=127.0.0.1:{port}'], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f'http://127.0.0.1:{port}'
        for _ in range(50):
            try:
                with urlopen(base+'/metrics', timeout=1):
                    break
            except URLError:
                assert process.poll() is None, 'Exporter rejected config'
                time.sleep(.1)
        else:
            raise AssertionError('Exporter did not start')

        def scrape():
            url = base+'/probe?'+urlencode({'module': 'queue', 'target': f'http://127.0.0.1:{server.server_port}/api'})
            try:
                with urlopen(url, timeout=5) as response:
                    text = response.read().decode()
            except HTTPError:
                return {}
            assert key not in text and 'private-title' not in text
            return {line.split()[0]: float(line.split()[1]) for line in text.splitlines() if line.startswith('sabnzbd_')}

        def queue(speed='2048.5', remaining='4096.25', jobs=3, paused=False):
            state['status'] = 200
            state['body'] = {'queue': {'kbpersec': speed, 'mbleft': remaining,
                'noofslots_total': jobs, 'paused': paused, 'slots': [{'filename': 'private-title'}]}}

        queue()
        assert scrape() == {'sabnzbd_download_kibibytes_per_second': 2048.5,
                            'sabnzbd_queue_remaining_mebibytes': 4096.25,
                            'sabnzbd_queue_jobs': 3, 'sabnzbd_queue_paused': 0}
        assert state['authenticated'], 'Expected a form POST with API key and read-only queue operation'
        queue(0, 0, 0)
        assert all(value == 0 for value in scrape().values()), 'Idle queue should be valid zeros'
        queue(0, 42, 2, True)
        result = scrape()
        assert result['sabnzbd_queue_paused'] == 1 and result['sabnzbd_queue_remaining_mebibytes'] == 42
        for field, metric in [('kbpersec', 'sabnzbd_download_kibibytes_per_second'),
                              ('mbleft', 'sabnzbd_queue_remaining_mebibytes')]:
            for value in (None, 'invalid'):
                queue()
                state['body']['queue'][field] = value
                assert metric not in scrape()
            queue()
            del state['body']['queue'][field]
            assert metric not in scrape()
        for body in ({}, {'error': 'API Key Incorrect'}, {'queue': {}}):
            state['body'] = body
            assert not scrape(), 'Malformed/error response must not become an idle queue'
        for status in (401, 403, 500, 302):
            queue()
            state['status'] = status
            assert not scrape()
        assert not state['redirected'], 'Do not forward the credential to redirects'
        print('SAB exporter: POST authentication, encoding, units, idle/paused queues, missing/invalid data, HTTP failures, redirects, and label privacy passed')
    finally:
        process.terminate()
        process.wait(timeout=5)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
