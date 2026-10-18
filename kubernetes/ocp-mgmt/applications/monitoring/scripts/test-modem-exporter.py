#!/usr/bin/env python3
"""Exercise Hitron HTTP sessions against a local fake modem; no real credentials."""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('modem_exporter', ROOT / 'modem/exporter.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
STATUS = {'errCode': '000', 'systemLanUptime': '1538', 'systemWanUptime': '1538',
          'wanRxPkts': '685399', 'wanTxPkts': '312957', 'modelName': 'CODA5610Q',
          'SoftwareVersion': '7.2.4.5.3b7', 'routerMode': 'Bridge',
          'SerialNum': 'DO-NOT-EXPORT', 'rfMac': 'DO-NOT-EXPORT', 'wanIP': 'DO-NOT-EXPORT'}


class Sessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.credentials = Path(self.temp.name)
        (self.credentials / 'username').write_text('test-user')
        (self.credentials / 'password').write_text('test secret+%&é')
        self.mode = 'normal'
        self.token = 0
        self.login_requests = []
        self.status_requests = 0
        test = self

        class ModemHandler(BaseHTTPRequestHandler):
            def send(self, body, code=200, headers=None):
                raw = body.encode()
                self.send_response(code)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                test.status_requests += 1
                if test.mode == 'redirect':
                    return self.send('', 302, {'Location': 'http://127.0.0.1:1/never-follow'})
                if test.mode == 'transport':
                    return self.send('unavailable', 503)
                if test.mode == 'invalid':
                    return self.send(json.dumps({'errCode': '000'}))
                if test.mode == 'expired' or self.headers.get('Cookie') != f'session={test.token}' or test.token == 0:
                    return self.send('<html>login</html>')
                self.send(json.dumps(STATUS))

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length'])).decode()
                test.login_requests.append((self.path, parse_qs(body)))
                if test.mode in ('reject', 'redirect'):
                    return self.send(json.dumps({'result': 'wrong_password'}))
                test.token += 1
                self.send(json.dumps({'result': 'success'}), headers={'Set-Cookie': f'session={test.token}; Path=/'})

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ModemHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.modem = exporter.Modem(f'http://127.0.0.1:{self.server.server_port}', self.credentials)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_login_cookie_reuse_and_expiration(self):
        self.assertEqual(self.modem.collect(), STATUS)
        self.assertEqual(self.modem.collect(), STATUS)
        self.assertEqual(len(self.login_requests), 1)
        self.token += 1  # Existing cookie is now invalid.
        self.assertEqual(self.modem.collect(), STATUS)
        self.assertEqual(len(self.login_requests), 2)
        path, form = self.login_requests[0]
        self.assertEqual(path, '/1/Device/Users/Login')
        self.assertEqual(json.loads(form['model'][0]),
                         {'username': 'test-user', 'password': 'test%20secret+%25%26%E9'})

    def test_rejected_login_has_no_retry_loop(self):
        self.mode = 'reject'
        with self.assertRaises(exporter.AuthenticationRequired):
            self.modem.collect()
        self.assertEqual(len(self.login_requests), 1)

    def test_login_success_without_session_is_still_failure(self):
        self.mode = 'expired'
        with self.assertRaises(exporter.AuthenticationRequired):
            self.modem.collect()
        self.assertEqual(len(self.login_requests), 1)

    def test_redirect_is_not_followed(self):
        self.mode = 'redirect'
        with self.assertRaises(exporter.AuthenticationRequired):
            self.modem.collect()
        self.assertEqual(len(self.login_requests), 1)

    def test_rotation_is_read_at_next_login(self):
        self.modem.collect()
        (self.credentials / 'password').write_text('rotated')
        self.token += 1
        self.modem.collect()
        self.assertEqual(json.loads(self.login_requests[-1][1]['model'][0])['password'], 'rotated')

    def test_failure_removes_old_data_without_failing_process_health(self):
        collector = exporter.Collector(self.modem)
        collector.poll()
        self.assertIn('hitron_wan_packets_total', collector.render())
        before = self.status_requests
        collector.render()
        collector.render()
        self.assertEqual(before, self.status_requests)  # Scrapes never contact modem.
        self.mode = 'transport'
        with redirect_stdout(io.StringIO()) as logs:
            collector.poll()
        output = collector.render()
        self.assertIn('hitron_collection_success 0', output)
        self.assertNotIn('hitron_wan_packets_total', output)
        self.assertTrue(collector.healthy())
        self.assertGreater(collector.last_success, 0)
        self.assertNotIn('test secret', logs.getvalue())

    def test_malformed_status_is_not_success(self):
        self.mode = 'invalid'
        collector = exporter.Collector(self.modem)
        with redirect_stdout(io.StringIO()):
            collector.poll()
        self.assertIn('hitron_collection_success 0', collector.render())

    def test_stalled_worker_expires_metrics_and_health(self):
        collector = exporter.Collector(self.modem)
        collector.poll()
        collector.last_finished -= 181
        self.assertNotIn('hitron_wan_packets_total', collector.render())
        self.assertFalse(collector.healthy())


class Payloads(unittest.TestCase):
    def test_only_allowlisted_fields_are_exported(self):
        text = exporter.telemetry(STATUS)
        self.assertIn('hitron_interface_uptime_seconds{interface="wan"} 1538', text)
        self.assertIn('hitron_wan_packets_total{direction="receive"} 685399', text)
        self.assertNotIn('DO-NOT-EXPORT', text)

    def test_invalid_values_and_label_escaping(self):
        for value in ['NaN', 'inf', '-1', '1.5', True, None]:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                exporter.telemetry(dict(STATUS, wanRxPkts=value))
        self.assertEqual(exporter.label('a"b\nc\\d'), 'a\\"b\\nc\\\\d')
        self.assertEqual(exporter.browser_escape('🛰'), '%uD83D%uDEF0')

    def test_rendered_wiring(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(['kustomize', 'build', str(ROOT)], text=True)))
        dep = next(x for x in docs if x['kind'] == 'Deployment' and x['metadata']['name'] == 'modem-exporter')
        pod = dep['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertTrue(pod['containers'][0]['securityContext']['readOnlyRootFilesystem'])
        secret = next(x for x in docs if x['kind'] == 'ExternalSecret' and x['metadata']['name'] == 'modem-login-v1')
        self.assertEqual({x['remoteRef']['property'] for x in secret['spec']['data']}, {'username', 'password'})
        self.assertTrue(all(x['remoteRef']['key'] == '769bd8e4-500b-4cf6-899f-b47c013712b2' for x in secret['spec']['data']))
        cmname = next(v for v in pod['volumes'] if v['name'] == 'config')['configMap']['name']
        cm = next(x for x in docs if x['kind'] == 'ConfigMap' and x['metadata']['name'] == cmname)
        self.assertEqual(cm['data']['exporter.py'], (ROOT / 'modem/exporter.py').read_text())


if __name__ == '__main__':
    unittest.main()
