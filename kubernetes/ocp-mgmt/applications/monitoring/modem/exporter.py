"""Hitron bridge-mode telemetry, using only Python's standard library."""
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class AuthenticationRequired(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the password/session to a redirect destination.
        return None


def browser_escape(value):
    """Match the login page's legacy JavaScript escape(), including UTF-16."""
    encoded = value.encode('utf-16-be')
    output = []
    for offset in range(0, len(encoded), 2):
        code = int.from_bytes(encoded[offset:offset + 2], 'big')
        char = chr(code)
        if char.isascii() and (char.isalnum() or char in '@*_+-./'):
            output.append(char)
        else:
            output.append(f'%{code:02X}' if code < 256 else f'%u{code:04X}')
    return ''.join(output)


class Modem:
    def __init__(self, base, credentials):
        self.base = base.rstrip('/')
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path:
            raise ValueError('Invalid modem base URL')
        self.credentials = Path(credentials)
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(self.cookies))
        self.login_attempts = 0

    def request(self, path, data=None):
        headers = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                   'Referer': self.base + '/webpages/index.html'}
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(65537)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code in (301, 302, 303, 307, 308, 401, 403):
                raise AuthenticationRequired() from None
            raise
        if len(raw) > 65536:
            raise ValueError('Oversize response')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            # This firmware serves the login HTML with HTTP 200 on expiry.
            raise AuthenticationRequired() from None
        if not isinstance(payload, dict):
            raise ValueError('Expected object')
        return payload

    def status(self):
        payload = self.request('/1/Device/Router/SysInfo')
        if payload.get('errCode') != '000':
            raise AuthenticationRequired()
        return payload

    def collect(self):
        try:
            return self.status()
        except AuthenticationRequired:
            # One login attempt per poll, never a retry loop or every scrape.
            self.cookies.clear()
            username = (self.credentials / 'username').read_text()
            password = (self.credentials / 'password').read_text()
            if not username or not password:
                raise ValueError('Empty credentials')
            model = json.dumps({'username': browser_escape(username),
                                'password': browser_escape(password)})
            body = urllib.parse.urlencode({'model': model}).encode()
            self.login_attempts += 1
            if self.request('/1/Device/Users/Login', body).get('result') != 'success':
                raise AuthenticationRequired()
            return self.status()


def number(payload, key):
    value = payload[key]
    if isinstance(value, bool):
        raise ValueError('Boolean counter')
    result = float(value)
    if not math.isfinite(result) or result < 0 or result != int(result):
        raise ValueError('Invalid counter')
    return int(result)


def label(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError('Invalid info label')
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def telemetry(payload):
    lines = ['# HELP hitron_interface_uptime_seconds Firmware-reported interface uptime; reset semantics are not yet verified.',
             '# TYPE hitron_interface_uptime_seconds gauge']
    for interface, key in [('lan', 'systemLanUptime'), ('wan', 'systemWanUptime')]:
        lines.append(f'hitron_interface_uptime_seconds{{interface="{interface}"}} {number(payload, key)}')
    lines.extend(['# HELP hitron_wan_packets_total Firmware-reported WAN packets; bridge-mode coverage requires validation.',
                  '# TYPE hitron_wan_packets_total counter'])
    for direction, key in [('receive', 'wanRxPkts'), ('transmit', 'wanTxPkts')]:
        lines.append(f'hitron_wan_packets_total{{direction="{direction}"}} {number(payload, key)}')
    info = ','.join(f'{name}="{label(payload[key])}"' for name, key in
                    [('model', 'modelName'), ('firmware', 'SoftwareVersion'), ('mode', 'routerMode')])
    lines.extend(['# HELP hitron_info Modem model, firmware and operating mode.',
                  '# TYPE hitron_info gauge', f'hitron_info{{{info}}} 1'])
    return '\n'.join(lines) + '\n'


class Collector:
    def __init__(self, modem):
        self.modem = modem
        self.lock = threading.Lock()
        self.body = ''
        self.success = False
        self.last_success = 0
        self.last_finished = time.monotonic()
        self.errors = 0
        self.duration = 0

    def poll(self):
        start = time.monotonic()
        body = ''
        reason = None
        try:
            body = telemetry(self.modem.collect())
        except AuthenticationRequired:
            reason = 'authentication'
        except OSError:
            reason = 'transport_or_credentials'
        except (ValueError, KeyError, TypeError, OverflowError):
            reason = 'invalid_payload'
        except Exception:
            # Never log exception strings: response bodies/URLs can be sensitive.
            reason = 'internal'
        with self.lock:
            self.success = reason is None
            self.body = body if self.success else ''
            self.errors += int(not self.success)
            if self.success:
                self.last_success = time.time()
            self.last_finished = time.monotonic()
            self.duration = self.last_finished - start
        if reason:
            print(f'modem collection failed: {reason}', flush=True)

    def render(self):
        with self.lock:
            fresh = time.monotonic() - self.last_finished < 150
            metrics = [
                ('hitron_collection_success', 'gauge', 'Most recent poll succeeded and is fresh.', int(self.success and fresh)),
                ('hitron_last_success_timestamp_seconds', 'gauge', 'Unix time of last successful poll, or zero.', self.last_success),
                ('hitron_collection_duration_seconds', 'gauge', 'Duration of the most recently completed poll.', self.duration),
                ('hitron_collection_errors_total', 'counter', 'Failed collection attempts.', self.errors),
                ('hitron_login_attempts_total', 'counter', 'Login requests attempted.', self.modem.login_attempts),
            ]
            output = ''.join(f'# HELP {name} {help_text}\n# TYPE {name} {kind}\n{name} {value}\n'
                             for name, kind, help_text, value in metrics)
            return output + (self.body if self.success and fresh else '')

    def healthy(self):
        with self.lock:
            return time.monotonic() - self.last_finished < 180


def handler(collector):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/metrics':
                body = collector.render().encode()
                code, content_type = 200, 'text/plain; version=0.0.4; charset=utf-8'
            elif self.path == '/healthz':
                code = 200 if collector.healthy() else 503
                body, content_type = b'collector\n', 'text/plain'
            else:
                code, body, content_type = 404, b'not found\n', 'text/plain'
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


def main():
    collector = Collector(Modem(os.environ.get('MODEM_URL', 'http://192.168.100.1'),
                                os.environ.get('CREDENTIALS_DIR', '/etc/modem-credentials')))

    def poll_forever():
        while True:
            start = time.monotonic()
            collector.poll()
            time.sleep(max(1, 60 - (time.monotonic() - start)))

    threading.Thread(target=poll_forever, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 9780), handler(collector)).serve_forever()


if __name__ == '__main__':
    main()
