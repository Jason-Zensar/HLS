"""Background ingestion worker.

A dispatcher thread polls the durable `jobs` table. CPU-heavy analysis runs in a process pool
(bounded by INGEST_WORKERS); persistence (SQLite + Neo4j) is serialised in this thread so graph
writes never contend. Jobs left "running" by an interrupted process are re-queued at start-up and
resume from their last checkpointed stage. Failed jobs keep their error and can be retried.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import Future, ProcessPoolExecutor

from app.config import get_settings
from app.core import metadb
from app.ingest import pipeline

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def _init_child():
    import logging as _l
    _l.basicConfig(level=_l.WARNING)


class IngestWorker:
    def __init__(self):
        self.s = get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool: ProcessPoolExecutor | None = None
        self.running: dict[str, tuple[str, Future, float]] = {}  # job_id -> (doc_id, future, started)
        self.paused = False

    def start(self):
        metadb.execute("UPDATE jobs SET status='queued', updated_at=? WHERE status='running'", (time.time(),))
        metadb.execute("UPDATE documents SET status='queued' WHERE status='processing'")
        self._pool = ProcessPoolExecutor(max_workers=max(1, self.s.ingest_workers), initializer=_init_child)
        self._thread = threading.Thread(target=self._loop, name="ingest-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def status(self) -> dict:
        return {"running_jobs": len(self.running), "workers": self.s.ingest_workers, "paused": self.paused,
                "queued": metadb.q1("SELECT count(*) c FROM jobs WHERE status='queued'")["c"]}

    # ------------------------------------------------------------------
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._collect()
                if not self.paused:
                    self._dispatch()
            except Exception:
                log.exception("worker loop error")
            time.sleep(0.5)

    def _dispatch(self):
        free = max(1, self.s.ingest_workers) - len(self.running)
        if free <= 0:
            return
        jobs = metadb.q("SELECT j.*, d.filename, d.stored_name, d.stage AS doc_stage FROM jobs j JOIN documents d ON d.id = j.doc_id "
                        "WHERE j.status='queued' ORDER BY j.created_at LIMIT ?", (free,))
        for j in jobs:
            now = time.time()
            metadb.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (now, j["id"]))
            metadb.execute("UPDATE documents SET status='processing' WHERE id=?", (j["doc_id"],))
            stage = j["doc_stage"] or "registered"
            if j["kind"] == "regraph" or pipeline.STAGES.index(stage) >= pipeline.STAGES.index("analyzed") \
                    and pipeline.load_artifact(j["doc_id"], "analysis") is not None:
                fut: Future = Future()
                fut.set_result({"doc_id": j["doc_id"], "skipped_analysis": True})
            else:
                fut = self._pool.submit(pipeline.analyze_document, j["doc_id"], str(self.s.pdf_dir / j["stored_name"]),
                                        j["filename"], stage)
            self.running[j["id"]] = (j["doc_id"], fut, now)
            metadb.audit("job.started", f"{j['kind']} started for {j['filename']} (resume after stage '{stage}')", j["doc_id"])

    def _collect(self):
        for job_id, (doc_id, fut, started) in list(self.running.items()):
            if not fut.done():
                continue
            del self.running[job_id]
            try:
                res = fut.result()
                if not res.get("skipped_analysis"):
                    metadb.execute("UPDATE documents SET stage='analyzed' WHERE id=?", (doc_id,))
                metadb.execute("UPDATE jobs SET stage='persisting', updated_at=? WHERE id=?", (time.time(), job_id))
                pipeline.persist_document(doc_id)
                metadb.execute("UPDATE jobs SET status='done', stage='done', updated_at=?, duration_s=?, error=NULL WHERE id=?",
                               (time.time(), round(time.time() - started, 1), job_id))
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                log.error("job %s failed: %s\n%s", job_id, err, traceback.format_exc())
                job = metadb.q1("SELECT attempts FROM jobs WHERE id=?", (job_id,))
                retry = job and job["attempts"] < MAX_ATTEMPTS and not isinstance(e, ValueError)
                metadb.execute("UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
                               ("queued" if retry else "failed", err[:2000], time.time(), job_id))
                metadb.execute("UPDATE documents SET status=?, error=? WHERE id=?",
                               ("queued" if retry else "failed", err[:2000], doc_id))
                metadb.execute("INSERT INTO warnings(doc_id, page, stage, severity, code, message) VALUES (?,?,?,?,?,?)",
                               (doc_id, None, "pipeline", "error", "processing_failed", err[:500]))
                metadb.audit("job.failed", err[:300], doc_id)


_worker: IngestWorker | None = None


def get_worker() -> IngestWorker:
    global _worker
    if _worker is None:
        _worker = IngestWorker()
    return _worker


def enqueue(doc_id: str, kind: str = "ingest", reset_stage: str | None = None) -> str:
    now = time.time()
    jid = metadb.new_id("job")
    with metadb.tx() as c:
        if reset_stage:
            c.execute("UPDATE documents SET stage=?, status='queued', error=NULL WHERE id=?", (reset_stage, doc_id))
        else:
            c.execute("UPDATE documents SET status='queued', error=NULL WHERE id=?", (doc_id,))
        c.execute("INSERT INTO jobs(id, doc_id, kind, status, stage, attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                  (jid, doc_id, kind, "queued", reset_stage or "resume", 0, now, now))
    return jid
