"""Internal LanceDB service for approved teaching questions and live-gated retrieval."""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import tempfile

from fastapi import FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from publication_contract import MAX_BODY
from question_index import ApprovalUnavailable, QuestionIndex, RevisionConflict
import lancedb


logger = logging.getLogger("uvicorn.error")


def create_app(data_dir=None):
    directory = Path(data_dir or os.environ.get("LANCEDB_DIR", "/data/lancedb"))

    @asynccontextmanager
    async def lifespan(app):
        directory.mkdir(parents=True, exist_ok=True)
        # Fail startup if the mounted volume cannot persist writes.
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".write-check-") as handle:
            handle.write(b"lancedb storage check\n")
            handle.flush()
            os.fsync(handle.fileno())
        app.state.db = lancedb.connect(directory)
        app.state.db.list_tables(limit=1)
        app.state.index = QuestionIndex(app.state.db)
        logger.info("LanceDB %s ready at %s", lancedb.__version__, directory)
        yield
        logger.info("LanceDB service stopped")

    app = FastAPI(title="RR lessons LanceDB", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            app.state.db.list_tables(limit=1)
        except Exception:
            logger.exception("LanceDB readiness check failed")
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return {"status": "ready", "lancedb_version": lancedb.__version__}

    @app.get("/v1/tables")
    def tables(limit: int = Query(default=100, ge=1, le=100),
               page_token: str | None = Query(default=None, max_length=2048)):
        try:
            result = app.state.db.list_tables(limit=limit, page_token=page_token)
        except Exception:
            logger.exception("LanceDB table listing failed")
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return {"tables": result.tables, "page_token": result.page_token}

    async def request_body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Use application/json')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise HTTPException(413, 'Publication request is too large')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, 'Invalid JSON') from None

    async def execute(operation, *args):
        try:
            return await run_in_threadpool(operation, *args)
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ApprovalUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            logger.exception('Question index operation failed')
            raise HTTPException(503, 'Question index unavailable') from None

    @app.put('/v1/questions/{question_id}')
    async def put_question(question_id: str, request: Request):
        return await execute(app.state.index.put, question_id, await request_body(request))

    @app.post('/v1/search')
    async def search_questions(request: Request):
        return await execute(app.state.index.search, await request_body(request))

    return app


app = create_app()
