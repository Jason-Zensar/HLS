"""Durable metadata store (SQLite, WAL mode).

Holds document records, ingestion jobs and checkpoints, extraction warnings, the
hierarchical sections / evidence chunks (with an FTS5 lexical index), tables,
entity-resolution review items, the audit log and query history.

The knowledge graph itself lives in Neo4j; this store is the system of record for
processing state and raw evidence text.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterable

from app.config import get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT,
    sha256 TEXT UNIQUE NOT NULL,
    size_bytes INTEGER,
    page_count INTEGER,
    doc_kind TEXT,                -- text | scanned | mixed
    status TEXT NOT NULL,         -- queued | processing | processed | failed
    stage TEXT,                   -- last completed stage
    error TEXT,
    uploaded_at REAL,
    processed_at REAL,
    nct_id TEXT,
    sponsor TEXT,
    sponsor_protocol_code TEXT,
    phase TEXT,
    version_label TEXT,
    version_date TEXT,
    amendment TEXT,
    document_type TEXT,           -- protocol | sap | protocol+sap | unknown
    entity_count INTEGER DEFAULT 0,
    relationship_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    table_count INTEGER DEFAULT 0,
    extraction_confidence REAL,
    stored_name TEXT NOT NULL,
    source TEXT                   -- upload | folder-import
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,           -- ingest | regraph
    status TEXT NOT NULL,         -- queued | running | done | failed
    stage TEXT,
    attempts INTEGER DEFAULT 0,
    error TEXT,
    created_at REAL,
    updated_at REAL,
    duration_s REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER,
    stage TEXT,
    severity TEXT,                -- info | warning | error
    code TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS ix_warn_doc ON warnings(doc_id);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_id TEXT,
    number TEXT,
    title TEXT,
    category TEXT,
    level INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    ord INTEGER,
    detection TEXT                -- toc | heading | default
);
CREATE INDEX IF NOT EXISTS ix_sections_doc ON sections(doc_id);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id TEXT,
    parent_chunk_id TEXT,
    chunk_type TEXT,              -- paragraph | list_item | table | table_row | heading_block
    page_start INTEGER,
    page_end INTEGER,
    section_title TEXT,
    section_category TEXT,
    text TEXT,
    bbox TEXT,                    -- JSON [[page, x0,y0,x1,y1], ...]
    extraction_method TEXT,
    extraction_confidence REAL,
    table_id TEXT,
    document_version TEXT,
    ord INTEGER
);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS ix_chunks_section ON chunks(section_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, chunk_id UNINDEXED, doc_id UNINDEXED, tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS doc_tables (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER,
    title TEXT,
    n_rows INTEGER,
    n_cols INTEGER,
    cells TEXT,                   -- JSON list of rows
    bbox TEXT,
    warnings TEXT
);
CREATE INDEX IF NOT EXISTS ix_tables_doc ON doc_tables(doc_id);

CREATE TABLE IF NOT EXISTS mentions (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    surface TEXT,
    page INTEGER
);
CREATE INDEX IF NOT EXISTS ix_mentions_entity ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS ix_mentions_doc ON mentions(doc_id);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_norm TEXT NOT NULL,
    source TEXT,                  -- lexicon | document | review
    PRIMARY KEY (entity_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS ix_alias_norm ON entity_aliases(alias_norm);

CREATE TABLE IF NOT EXISTS resolution_review (
    id TEXT PRIMARY KEY,
    doc_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    surface TEXT,
    surface_norm TEXT,
    entity_type TEXT,
    provisional_entity_id TEXT,
    candidate_entity_id TEXT,
    candidate_name TEXT,
    score REAL,
    reason TEXT,
    status TEXT,                  -- pending | merged | rejected
    decided_at REAL,
    context TEXT
);
CREATE INDEX IF NOT EXISTS ix_review_status ON resolution_review(status);

CREATE TABLE IF NOT EXISTS resolution_decisions (
    surface_norm TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    decision TEXT NOT NULL,       -- merge | separate
    target_entity_id TEXT,
    decided_at REAL,
    PRIMARY KEY (surface_norm, entity_type)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    kind TEXT,
    doc_id TEXT,
    message TEXT,
    payload TEXT
);

CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    ts REAL,
    question TEXT,
    mode TEXT,                    -- natural | structured
    intent TEXT,
    plan TEXT,
    n_nodes INTEGER,
    n_edges INTEGER,
    validation_status TEXT,
    latency_ms REAL,
    response TEXT
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    ts REAL,
    summary TEXT,
    details TEXT
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    s = get_settings()
    conn = sqlite3.connect(str(s.sqlite_path), timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def init_db() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = _connect()
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()
        _initialized = True


def conn() -> sqlite3.Connection:
    init_db()
    c = getattr(_local, "conn", None)
    if c is None:
        c = _connect()
        _local.conn = c
    return c


@contextmanager
def tx():
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def q(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, tuple(params)).fetchall()]


def q1(sql: str, params: Iterable[Any] = ()) -> dict | None:
    r = conn().execute(sql, tuple(params)).fetchone()
    return dict(r) if r else None


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with tx() as c:
        c.execute(sql, tuple(params))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def audit(kind: str, message: str, doc_id: str | None = None, payload: Any = None) -> None:
    execute(
        "INSERT INTO audit(ts, kind, doc_id, message, payload) VALUES (?,?,?,?,?)",
        (time.time(), kind, doc_id, message, json.dumps(payload, default=str) if payload is not None else None),
    )
