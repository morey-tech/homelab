"""Lesson desk API with a durable, single-consumer episode intake queue."""

import json
import logging
import os
from pathlib import Path
import sqlite3

from store import APIError, MIGRATION, StoreMixin


LOG = logging.getLogger("uvicorn.error")
SCHEMA_VERSION = 2
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/state.mjs": ("state.mjs", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE episodes (
    id TEXT PRIMARY KEY NOT NULL,
    episode_number INTEGER NOT NULL CHECK (episode_number > 0),
    title TEXT NOT NULL,
    source_json TEXT NOT NULL CHECK (json_valid(source_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE sections (
    id TEXT PRIMARY KEY NOT NULL,
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    source_json TEXT NOT NULL CHECK (json_valid(source_json)),
    UNIQUE (episode_id, ordinal)
);
CREATE TABLE questions (
    id TEXT PRIMARY KEY NOT NULL,
    section_id TEXT NOT NULL REFERENCES sections(id),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE reviews (
    question_id TEXT PRIMARY KEY NOT NULL REFERENCES questions(id),
    state_json TEXT NOT NULL CHECK (json_valid(state_json)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
PRAGMA user_version = 1;
COMMIT;
"""


class Database(StoreMixin):
    def __init__(self, path):
        self.path = Path(path).resolve()

    def connect(self):
        # Do not silently create a replacement database during a readiness check.
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        created = not self.path.exists()
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.executescript(SCHEMA)
                version = 1
            if version == 1:
                connection.executescript(MIGRATION)
            elif version != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported review database schema {version}")
        finally:
            connection.close()
        if created:
            # Permit future pods using a different SCC-assigned UID in the PVC group.
            self.path.chmod(0o660)
        self.counts()
        LOG.info("Review database ready: schema=%s, no sample data seeded", SCHEMA_VERSION)

    def counts(self):
        connection = self.connect()
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise RuntimeError("Unsupported review database schema")
            # One read transaction keeps counts consistent during future imports.
            connection.execute("BEGIN")
            connection.execute("SELECT 1 FROM ingestion_jobs LIMIT 0")
            return {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                    for name in ("episodes", "sections", "questions", "reviews")}
        finally:
            connection.close()


class ReviewApp:
    def __init__(self, database, static_dir, worker=None, public_origin=None):
        self.worker = worker
        self.public_origin = public_origin
        self.database = database
        self.static_dir = Path(static_dir)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    try:
                        self.database.initialize()
                        for filename, _ in ASSETS.values():
                            (self.static_dir / filename).read_bytes()
                        if self.worker:
                            self.worker.start()
                    except Exception:
                        LOG.exception("Review service initialization failed")
                        await send({"type": "lifespan.startup.failed", "message": "Review service initialization failed"})
                        return
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    if self.worker:
                        self.worker.stop()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            status, content_type, body = 200, "application/json", None
            path = scope["path"]
            if scope["method"] not in ("GET", "HEAD"):
                try:
                    if not (scope["method"] == "POST" and path == "/api/ingestions" or
                            scope["method"] == "PUT" and path.startswith("/api/reviews/")):
                        raise APIError("Method not allowed.", 405)
                    payload = await self.read_write(scope, receive)
                    if path == "/api/ingestions":
                        if not self.worker:
                            raise APIError("Ingestion is not configured on this instance.", 503)
                        if not isinstance(payload, dict) or set(payload) != {"episode"}:
                            raise APIError("Provide an episode number.")
                        body = self.database.enqueue(payload["episode"])
                        status = 202
                    else:
                        body = self.database.save_review(path.removeprefix("/api/reviews/"), payload)
                except APIError as exc:
                    status, body = exc.status, {"error": str(exc)}
                except sqlite3.Error:
                    LOG.exception("Review write failed")
                    status, body = 503, {"error": "Database unavailable; your changes were not saved."}
            elif path == "/healthz":
                body = {"status": "ok"}
            elif path == "/runtime.json":
                body = {"mode": "server", "apiVersion": 1}
            elif path in ("/readyz", "/api/inbox", "/api/ingestions"):
                try:
                    self.database.counts()
                    if path == "/readyz":
                        body = {"status": "ready", "schemaVersion": SCHEMA_VERSION}
                    elif path == "/api/ingestions":
                        body = {"jobs": self.database.jobs()}
                    else:
                        body = self.database.inbox()
                except (sqlite3.Error, RuntimeError):
                    LOG.exception("Review database unavailable")
                    status, body = 503, {"error": "Review database unavailable"}
            elif path in ASSETS:
                filename, content_type = ASSETS[path]
                try:
                    body = (self.static_dir / filename).read_bytes()
                except OSError:
                    status, content_type, body = 503, "application/json", {"error": "Review UI unavailable"}
            else:
                status, body = 404, {"error": "Not found"}
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            headers = [
                (b"content-type", content_type.encode()), (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                (b"referrer-policy", b"same-origin"), (b"x-frame-options", b"DENY"),
                (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
            ]
            if status == 405:
                headers.append((b"allow", b"GET, HEAD"))
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})


    async def read_write(self, scope, receive):
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        # JSON + exact Origin prevent cross-site browser submissions. This is not login/auth.
        origin = self.public_origin or f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
        if headers.get('origin') != origin or headers.get('sec-fetch-site') == 'cross-site':
            raise APIError('Write requests must come from this review workspace.', 403)
        if headers.get('content-type', '').split(';')[0] != 'application/json':
            raise APIError('Use application/json.', 415)
        raw = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                raise APIError('Request disconnected.')
            raw.extend(message.get('body', b''))
            if len(raw) > 32768:
                raise APIError('Request body is too large.', 413)
            if not message.get('more_body'):
                break
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise APIError('Invalid JSON.') from None


database = Database(Path(os.environ.get("REVIEW_DB_PATH", "/data/reviews.sqlite3")).resolve())
worker = None
if os.environ.get('INGESTION_ENABLED') == 'true':
    from pipeline import Pipeline, Worker
    # Shared PVC group must be able to reopen SQLite, Git objects and checkpoints.
    os.umask(0o007)
    worker = Worker(database, Pipeline(database, database.path.parent / 'ingestion',
                                      os.environ.get('MODEL_TOKEN_PATH', '/var/run/model-auth/token')))
app = ReviewApp(database, os.environ.get("REVIEW_STATIC_DIR", "/ui"), worker,
                os.environ.get('REVIEW_PUBLIC_ORIGIN'))
