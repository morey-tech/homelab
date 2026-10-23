import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


MODULE = Path(__file__).with_name("launch.py")
spec = importlib.util.spec_from_file_location("hermes_launch", MODULE)
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_seed_preserves_existing_state(self):
        config = self.root / "config"
        config.mkdir()
        (config / "SOUL.md").write_text("template")
        state = self.root / "state"
        launch.seed_state(state, config)
        self.assertEqual((state / "SOUL.md").read_text(), "template")
        (state / "SOUL.md").write_text("personalized")
        (state / "config.yaml").write_text("custom: true\n")
        launch.seed_state(state, config)
        self.assertEqual((state / "SOUL.md").read_text(), "personalized")
        self.assertEqual((state / "config.yaml").read_text(), "custom: true\n")

    def test_empty_credential_rejected(self):
        path = self.root / "key"
        path.write_text(" \n")
        with self.assertRaises(ValueError):
            launch.read_credentials({"KEY": path})

    def start_supervisor(self, child_code):
        key = self.root / "key"
        key.write_text("first-test-key")
        ready = self.root / "ready"
        code = (f"import sys;sys.path.insert(0,{str(MODULE.parent)!r});"
                "from launch import supervise;from pathlib import Path;"
                f"raise SystemExit(supervise([{sys.executable!r},'-c',{child_code!r}],"
                f"{{'TEST_KEY':Path({str(key)!r})}},poll_seconds=0.1,grace_seconds=1))")
        process = subprocess.Popen([sys.executable, "-B", "-c", code],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        return process, key, ready

    def wait_for_file(self, path, process):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.02)
        self.assertTrue(path.exists(), "child did not become ready")

    def sleeper(self):
        return ("import os,time;from pathlib import Path;"
                f"Path({str(self.root / 'ready')!r}).write_text(os.environ['TEST_KEY']);"
                "time.sleep(30)")

    def test_rotation_restarts_without_logging_secret(self):
        process, key, ready = self.start_supervisor(self.sleeper())
        self.wait_for_file(ready, process)
        self.assertEqual(ready.read_text(), "first-test-key")
        key.write_text("second-test-key")
        out, err = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, err)
        self.assertIn("restarting Hermes", out)
        self.assertNotIn("first-test-key", out + err)
        self.assertNotIn("second-test-key", out + err)

    def test_transient_missing_or_empty_projection_keeps_process_running(self):
        process, key, ready = self.start_supervisor(self.sleeper())
        self.wait_for_file(ready, process)
        key.unlink()
        time.sleep(0.3)
        self.assertIsNone(process.poll())
        key.write_text("")
        time.sleep(0.3)
        self.assertIsNone(process.poll())
        key.write_text("first-test-key")
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0)

    def test_child_failure_is_propagated(self):
        process, _, _ = self.start_supervisor("raise SystemExit(7)")
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 7)


if __name__ == "__main__":
    unittest.main()
