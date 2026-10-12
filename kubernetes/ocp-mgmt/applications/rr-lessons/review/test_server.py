import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server import ASSETS, Database, ReviewApp


class ReviewServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = Database(root / "data" / "reviews.sqlite3")
        self.static = root / "static"
        self.static.mkdir()
        for filename, _ in ASSETS.values():
            (self.static / filename).write_text("fixture asset")
        self.app = ReviewApp(self.database, self.static)
        self.database.initialize()

    async def request(self, path, method="GET"):
        sent = []

        async def send(event):
            sent.append(event)

        async def receive():
            return {"type": "http.request", "body": b""}

        await self.app({"type": "http", "method": method, "path": path}, receive, send)
        return sent[0]["status"], dict(sent[0]["headers"]), sent[1]["body"]

    async def test_fresh_database_and_inbox_are_empty(self):
        status, _, body = await self.request("/api/inbox")
        self.assertEqual(status, 200)
        inbox = json.loads(body)
        self.assertEqual(inbox["counts"], {"episodes": 0, "sections": 0, "questions": 0, "reviews": 0})
        self.assertTrue(inbox["reviewEnabled"])
        self.assertEqual(json.loads((await self.request("/runtime.json"))[2])["mode"], "server")
        self.assertEqual(self.database.path.stat().st_mode & 0o777, 0o660)

    async def test_restart_preserves_rows_and_relational_constraints(self):
        connection = self.database.connect()
        try:
            connection.execute("INSERT INTO episodes(id,episode_number,title,source_json) VALUES('test',1,'Persistence fixture','{}')")
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO sections VALUES('orphan','missing',0,'{}')")
        finally:
            connection.close()
        restarted = Database(self.database.path)
        restarted.initialize()
        self.assertEqual(restarted.counts()["episodes"], 1)
        self.assertEqual(json.loads((await self.request("/api/inbox"))[2])["counts"]["episodes"], 1)

    async def test_unregistered_write_routes_and_private_files_are_unavailable(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            status, headers, _ = await self.request("/api/inbox", method)
            self.assertEqual(status, 405)
            self.assertEqual(headers[b"allow"], b"GET, HEAD")
        for path in ("/sample.json", "/server.py", "/data/reviews.sqlite3", "/../server.py", "/api/import"):
            self.assertEqual((await self.request(path))[0], 404)
        self.assertEqual(self.database.counts()["episodes"], 0)

    async def test_database_failure_is_not_reported_as_an_empty_inbox(self):
        self.database.path.unlink()
        with self.assertLogs("uvicorn.error", level="ERROR"):
            self.assertEqual((await self.request("/api/inbox"))[0], 503)
            self.assertEqual((await self.request("/readyz"))[0], 503)
        self.assertEqual((await self.request("/healthz"))[0], 200)
        self.assertFalse(self.database.path.exists())

    async def test_assets_head_and_headers(self):
        status, headers, body = await self.request("/")
        self.assertEqual((status, body), (200, b"fixture asset"))
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertIn(b"frame-ancestors 'none'", headers[b"content-security-policy"])
        self.assertEqual((await self.request("/", "HEAD"))[2], b"")

    async def test_newer_schema_is_rejected_without_changes(self):
        connection = self.database.connect()
        connection.execute("PRAGMA user_version = 99")
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            self.database.initialize()
        connection = self.database.connect()
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
        connection.close()

    async def test_lifespan_checks_assets_and_initializes_database(self):
        sent = []
        events = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive():
            return next(events)

        async def send(event):
            sent.append(event)

        await self.app({"type": "lifespan"}, receive, send)
        self.assertEqual([event["type"] for event in sent], ["lifespan.startup.complete", "lifespan.shutdown.complete"])
        (self.static / "app.js").unlink()
        events = iter([{"type": "lifespan.startup"}])
        with self.assertLogs("uvicorn.error", level="ERROR"):
            await self.app({"type": "lifespan"}, receive, send)
        self.assertEqual(sent[-1]["type"], "lifespan.startup.failed")


if __name__ == "__main__":
    unittest.main()
