"""Internal LanceDB health and inspection service; retrieval is added separately."""

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import tempfile

from fastapi import FastAPI, HTTPException, Query
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

    return app


app = create_app()
