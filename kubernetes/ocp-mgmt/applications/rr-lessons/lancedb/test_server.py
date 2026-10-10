"""Run the real HTTP service against temporary LanceDB storage, without a cluster."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler, Request

import lancedb


@contextmanager
def running_server(directory):
    with socket.socket() as listener, tempfile.TemporaryFile(mode="w+t") as logs:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--fd", str(listener.fileno()), "--no-access-log"],
            cwd=Path(__file__).parent, env=os.environ | {"LANCEDB_DIR": str(directory)},
            pass_fds=(listener.fileno(),), stdout=logs, stderr=subprocess.STDOUT)
        client = build_opener(ProxyHandler({}))
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with client.open(url + "/readyz", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                logs.seek(0)
                raise AssertionError("Service did not become ready: " + logs.read())
            yield url, client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class LanceDBServiceTest(unittest.TestCase):
    def test_empty_storage_health_and_read_only_api(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "database"
            with running_server(directory) as (url, client):
                for route, expected in (("/healthz", {"status": "ok"}),
                                        ("/readyz", {"status": "ready", "lancedb_version": lancedb.__version__}),
                                        ("/v1/tables", {"tables": [], "page_token": None})):
                    with client.open(url + route) as response:
                        self.assertEqual(json.load(response), expected)
                for route, method, status in (("/v1/tables?limit=101", "GET", 422),
                                              ("/v1/tables", "POST", 405), ("/missing", "GET", 404)):
                    with self.assertRaises(HTTPError) as error:
                        client.open(Request(url + route, method=method))
                    self.assertEqual(error.exception.code, status)
                    error.exception.close()
            self.assertTrue(directory.is_dir())
            self.assertFalse(list(directory.glob(".write-check-*")))

    def test_persisted_tables_and_vectors_survive_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db = lancedb.connect(directory)
            db.create_table("alpha", [{"id": 1, "vector": [1.0, 0.0], "text": "persistent fixture"}])
            db.create_table("beta", [{"id": 2, "vector": [0.0, 1.0], "text": "second fixture"}])
            for _ in range(2):
                with running_server(directory) as (url, client):
                    with client.open(url + "/v1/tables") as response:
                        self.assertEqual(json.load(response)["tables"], ["alpha", "beta"])
                    with client.open(url + "/v1/tables?limit=1") as response:
                        page = json.load(response)
                        self.assertEqual(page["tables"], ["alpha"])
                        self.assertTrue(page["page_token"])
                    with client.open(url + "/v1/tables?" + urlencode({"page_token": page["page_token"]})) as response:
                        self.assertEqual(json.load(response)["tables"], ["beta"])
                reopened = lancedb.connect(directory).open_table("alpha")
                result = reopened.search([1.0, 0.0]).limit(1).to_list()
                self.assertEqual(result[0]["text"], "persistent fixture")


if __name__ == "__main__":
    unittest.main()
