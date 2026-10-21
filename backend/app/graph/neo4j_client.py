"""Neo4j access.

* Writes use the configured admin account (ingestion only).
* Every query-time read goes through `read()`: a read-only transaction (READ access mode,
  `execute_read`) with a timeout, optionally under a separate least-privilege `reader` account.
  Query text is never taken from the user - only allowlisted templates with parameters.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from neo4j import READ_ACCESS, GraphDatabase, Driver, unit_of_work

from app.config import get_settings
from app.graph.schema import RELATIONSHIPS

log = logging.getLogger(__name__)
_lock = threading.Lock()
_writer: Driver | None = None
_reader: Driver | None = None


def writer() -> Driver:
    global _writer
    with _lock:
        if _writer is None:
            s = get_settings()
            _writer = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password), max_connection_pool_size=20)
        return _writer


def reader() -> Driver:
    global _reader
    s = get_settings()
    if not s.neo4j_read_user:
        return writer()
    with _lock:
        if _reader is None:
            _reader = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_read_user, s.neo4j_read_password), max_connection_pool_size=20)
        return _reader


def close() -> None:
    global _writer, _reader
    for d in (_writer, _reader):
        if d is not None:
            d.close()
    _writer = _reader = None


def write(cypher: str, params: dict | None = None, database: str | None = None) -> list[dict]:
    s = get_settings()
    with writer().session(database=database or s.neo4j_database) as sess:
        return sess.execute_write(lambda tx: [r.data() for r in tx.run(cypher, params or {})])


def read(cypher: str, params: dict | None = None, *, timeout: float | None = None, database: str | None = None) -> list[dict]:
    s = get_settings()
    t = timeout or s.query_timeout_s

    @unit_of_work(timeout=t)
    def work(tx):
        return [r.data() for r in tx.run(cypher, params or {})]

    with reader().session(database=database or s.neo4j_database, default_access_mode=READ_ACCESS) as sess:
        return sess.execute_read(work)


def read_records(cypher: str, params: dict | None = None, *, timeout: float | None = None) -> list[Any]:
    """Like read() but returns raw records so Node / Relationship objects keep their element ids."""
    s = get_settings()

    @unit_of_work(timeout=timeout or s.query_timeout_s)
    def work(tx):
        return list(tx.run(cypher, params or {}))

    with reader().session(database=s.neo4j_database, default_access_mode=READ_ACCESS) as sess:
        return sess.execute_read(work)


def ensure_database() -> None:
    """Create the platform database (Enterprise) and the read-only account when configured."""
    s = get_settings()
    with writer().session(database="system") as sess:
        try:
            names = [r["name"] for r in sess.run("SHOW DATABASES YIELD name")]
            if s.neo4j_database not in names:
                sess.run(f"CREATE DATABASE `{s.neo4j_database}` IF NOT EXISTS WAIT")
        except Exception as e:  # Community edition: single database only -> fall back to the default "neo4j" database
            log.warning("Could not create database %s (%s); using default database 'neo4j'", s.neo4j_database, e)
            s.neo4j_database = "neo4j"
        if s.neo4j_read_user and s.neo4j_read_password:
            try:
                users = [r["user"] for r in sess.run("SHOW USERS YIELD user")]
                if s.neo4j_read_user not in users:
                    sess.run(f"CREATE USER `{s.neo4j_read_user}` SET PASSWORD $p CHANGE NOT REQUIRED", p=s.neo4j_read_password)
                sess.run(f"GRANT ROLE reader TO `{s.neo4j_read_user}`")
            except Exception as e:
                log.warning("Could not provision read-only user: %s", e)


def init_schema() -> None:
    ensure_database()
    stmts = [
        "CREATE CONSTRAINT kg_id IF NOT EXISTS FOR (n:KG) REQUIRE n.id IS UNIQUE",
        "CREATE INDEX kg_doc IF NOT EXISTS FOR (n:KG) ON (n.doc_id)",
        "CREATE INDEX kg_scope IF NOT EXISTS FOR (n:KG) ON (n.scope)",
        "CREATE INDEX kg_type IF NOT EXISTS FOR (n:KG) ON (n.type)",
        "CREATE INDEX kg_name IF NOT EXISTS FOR (n:KG) ON (n.name_norm)",
        "CREATE FULLTEXT INDEX kg_names IF NOT EXISTS FOR (n:KG) ON EACH [n.name, n.aliases_text]",
    ]
    for rel in RELATIONSHIPS:
        stmts.append(f"CREATE INDEX rel_doc_{rel.lower()} IF NOT EXISTS FOR ()-[r:{rel}]-() ON (r.source_document_id)")
    for st in stmts:
        write(st)
