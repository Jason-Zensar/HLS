"""CTPIP - Clinical Trial Protocol Intelligence Platform (FastAPI application)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import assistant, documents, evaluation, graph, query
from app.config import PROJECT_ROOT, get_settings
from app.core import metadb
from app.graph import neo4j_client as db
from app.ingest.worker import get_worker
from app.llm import settings as ai_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ctpip")
STATE = {"graph": "unknown", "graph_error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    metadb.init_db()
    ai_settings.init()
    try:
        db.init_schema()
        STATE["graph"] = "online"
    except Exception as e:  # the API still serves documents / history; graph endpoints report the outage
        STATE["graph"], STATE["graph_error"] = "unavailable", f"{type(e).__name__}: {e}"
        log.error("Neo4j unavailable at startup: %s", e)
    from app.extraction.entities import base_matcher
    base_matcher()  # warm the terminology matcher
    get_worker().start()
    _auto_import_if_empty()
    log.info("CTPIP ready (graph: %s)", STATE["graph"])
    yield
    get_worker().stop()
    db.close()


def _auto_import_if_empty() -> None:
    """First start on a new computer: queue the bundled dataset so the system fills itself."""
    if not get_settings().auto_import_on_empty or metadb.q1("SELECT count(*) c FROM documents")["c"]:
        return
    import threading

    def run():
        try:
            r = documents.import_dataset_folder()
            log.info("Empty document store: auto-import queued %s PDFs (%s duplicates)", r.queued, r.duplicates)
        except Exception:
            log.exception("Auto-import failed")
    threading.Thread(target=run, name="auto-import", daemon=True).start()


app = FastAPI(
    title="Clinical Trial Protocol Intelligence Platform",
    version="1.0.0",
    description="Document-grounded, provenance-aware knowledge graph over clinical trial protocols. "
                "All graph reads are read-only allowlisted templates; no raw Cypher is accepted.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def token_guard(request: Request, call_next):
    token = get_settings().api_token
    if token and request.url.path.startswith("/api") and request.url.path != "/api/health":
        if request.headers.get("X-API-Token") != token:
            return JSONResponse({"detail": "missing or invalid API token"}, status_code=401)
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    msg = type(exc).__name__
    if "ServiceUnavailable" in msg or "Neo4j" in msg:
        return JSONResponse({"detail": "Graph database unavailable", "error": msg}, status_code=503)
    return JSONResponse({"detail": "Internal error", "error": msg}, status_code=500)


@app.get("/api/health", tags=["system"])
def health():
    graph = STATE["graph"]
    try:
        db.read("RETURN 1 AS ok", timeout=3)
        graph = "online"
    except Exception as e:
        graph = f"unavailable: {type(e).__name__}"
    s = get_settings()
    return {"status": "ok", "graph": graph, "database": s.neo4j_database, "read_only_user": bool(s.neo4j_read_user),
            "worker": get_worker().status(), "extraction_provider": s.extraction_provider, "answer_provider": s.answer_provider,
            "ocr_enabled": s.ocr_enabled, "ai": {k: v for k, v in ai_settings.get().items() if k in ("enabled", "provider", "model")}}


for r in (documents.router, documents.jobs_router, graph.router, graph.entities_router, query.router, evaluation.router, assistant.router):
    app.include_router(r)

# ---- built frontend (single-port deployment; checked per request so a later build is picked up) ----
DIST = PROJECT_ROOT / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if not (DIST / "index.html").exists():
        return JSONResponse({"detail": "Frontend not built. Run: cd frontend && npm install && npm run build "
                                       "(start.bat does this automatically)."}, status_code=503)
    f = (DIST / full_path).resolve()
    if full_path and f.is_file() and DIST.resolve() in f.parents:
        return FileResponse(f)
    return FileResponse(DIST / "index.html")
