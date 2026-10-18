#!/usr/bin/env python3
"""Run the actual shell health check with controlled metrics and child processes.

No cluster or network access. Command doubles stand in only for wget, sleep,
and the diagnostic prober; parsing, comparison and cleanup run unchanged.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def metrics(sent=100, replies=90, *, google=90, process=1000, fatal=0):
    lines = [f'process_start_time_seconds {process}', f'smokeping_prober_errors_total {fatal}']
    for target, received, scope in [('cloudflare', replies, 'internet'),
                                     ('google', google, 'internet'), ('pfsense', sent, 'lan')]:
        labels = f'host="1.1.1.1",scope="{scope}",target="{target}"'
        lines.extend([f'smokeping_requests_total{{{labels}}} {sent}',
                      f'smokeping_response_duration_seconds_count{{{labels}}} {received}'])
    return '\n'.join(lines) + '\n'


DOUBLE = '''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
root = Path(os.environ['FIXTURE'])
fixture = json.loads((root / 'fixture.json').read_text())
command = Path(sys.argv[0]).name
if command == 'sleep':
    time.sleep(0.1)
elif command == 'smokeping_prober':
    (root / 'child.json').write_text(json.dumps({'pid': os.getpid(), 'args': sys.argv[1:]}))
    if fixture.get('child_failure'):
        sys.exit(1)
    time.sleep(60)
elif command == 'wget':
    if ':19374/' in sys.argv[-1]:
        value = fixture['fresh']
    else:
        counter = root / 'reads'
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
        value = fixture['original'][n]
    if value is None:
        sys.exit(1)
    print(value, end='')
'''


class HealthCheck(unittest.TestCase):
    def run_check(self, original, fresh=None, expected=0, diagnostic=True, child_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'fixture.json').write_text(json.dumps({
                'original': original, 'fresh': fresh, 'child_failure': child_failure}))
            for command in ['wget', 'sleep', 'smokeping_prober']:
                path = root / command
                path.write_text(DOUBLE)
                path.chmod(0o755)
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}',
                       FIXTURE=str(root), HEALTH_WORK_DIR=str(root))
            result = subprocess.run(['sh', str(ROOT / 'internet/check-health.sh')],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, expected, result.stderr)
            child = root / 'child.json'
            self.assertEqual(child.exists(), diagnostic, result.stderr)
            if child.exists():
                info = json.loads(child.read_text())
                self.assertIn('--web.listen-address=127.0.0.1:19374', info['args'])
                # Child must be reaped on success, failure, and failed startup.
                with self.assertRaises(ProcessLookupError):
                    os.kill(info['pid'], 0)
            self.assertFalse(list(root.glob('check.*')), 'temporary files leaked')
            return result.stderr

    def test_healthy_and_partial_loss_need_no_diagnostic(self):
        self.run_check([metrics(), metrics(105, 91, google=95)], diagnostic=False)

    def test_real_outage_does_not_restart(self):
        self.run_check([metrics(), metrics(105), metrics(115)], metrics(10, 0, google=0))

    def test_fresh_success_confirms_stuck_session(self):
        message = self.run_check([metrics(), metrics(105), metrics(115)],
                                metrics(10, 9, google=9), expected=1)
        self.assertIn('Stuck ping session', message)
        self.assertIn('cloudflare', message)

    def test_one_stuck_target_can_recover(self):
        self.run_check([metrics(), metrics(105, google=95), metrics(115, google=105)],
                       metrics(10, 8, google=8), expected=1)

    def test_success_from_other_target_does_not_restart(self):
        self.run_check([metrics(), metrics(105, google=95), metrics(115, google=105)],
                       metrics(10, 0, google=9))

    def test_natural_recovery_during_confirmation(self):
        self.run_check([metrics(), metrics(105), metrics(115, 91, google=91)],
                       metrics(10, 9, google=9))

    def test_only_a_few_fresh_replies_is_inconclusive(self):
        self.run_check([metrics(), metrics(105), metrics(115)], metrics(10, 2, google=4))

    def test_restart_during_initial_observation(self):
        self.run_check([metrics(), metrics(5, 0, google=0, process=2000)], diagnostic=False)

    def test_restart_during_confirmation(self):
        self.run_check([metrics(), metrics(105), metrics(5, 0, google=0, process=2000)],
                       metrics(10, 9, google=9))

    def test_unavailable_diagnostic_is_not_outage_recovery(self):
        self.run_check([metrics(), metrics(105)], fresh=None)

    def test_failed_child_is_reaped(self):
        self.run_check([metrics(), metrics(105)], child_failure=True)

    def test_primary_metrics_failure_during_confirmation_cleans_up(self):
        self.run_check([metrics(), metrics(105), None], metrics(10, 9, google=9), expected=1)

    def test_malformed_fresh_metrics_are_inconclusive(self):
        self.run_check([metrics(), metrics(105)], fresh='invalid metrics')

    def test_fatal_pinger_still_fails_liveness(self):
        self.run_check([metrics(fatal=1)], expected=1, diagnostic=False)

    def test_missing_or_invalid_primary_metrics_fail_liveness(self):
        for value in [None, '', metrics().replace('smokeping_prober_errors_total 0\n', ''),
                      metrics().replace('scope="internet"', 'scope="lan"'),
                      metrics().replace('} 90', '} NaN')]:
            with self.subTest(value=value):
                self.run_check([value], expected=1, diagnostic=False)

    def test_rendered_deployment_mounts_the_check_and_scratch_space(self):
        rendered = subprocess.check_output(['kustomize', 'build', str(ROOT)], text=True)
        resources = list(yaml.safe_load_all(rendered))
        deployment = next(r for r in resources if r['kind'] == 'Deployment'
                          and r['metadata']['name'] == 'smokeping-prober')
        pod = deployment['spec']['template']['spec']
        container = pod['containers'][0]
        probe = container['livenessProbe']
        self.assertEqual(probe['exec']['command'], ['/bin/sh', '/etc/smokeping/check-health.sh'])
        self.assertEqual(probe['failureThreshold'], 3)
        self.assertGreater(probe['timeoutSeconds'], 5 + 10 + 4 * 3)
        self.assertGreater(probe['periodSeconds'], probe['timeoutSeconds'])
        self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual(container['securityContext']['capabilities'], {'drop': ['ALL']})
        mounts = {m['mountPath']: m for m in container['volumeMounts']}
        volumes = {v['name']: v for v in pod['volumes']}
        self.assertEqual(volumes[mounts['/var/run/smokeping-health']['name']]['emptyDir'],
                         {'medium': 'Memory', 'sizeLimit': '8Mi'})
        config_name = volumes[mounts['/etc/smokeping']['name']]['configMap']['name']
        config = next(r for r in resources if r['kind'] == 'ConfigMap'
                      and r['metadata']['name'] == config_name)
        for name in ['smokeping.yml', 'check-health.sh', 'ping-snapshot.awk']:
            self.assertEqual(config['data'][name], (ROOT / 'internet' / name).read_text())


if __name__ == '__main__':
    unittest.main()
