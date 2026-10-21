"""Query, evidence, comparison, quality, history and dashboard endpoints."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import metadb
from app.graph import neo4j_client as db
from app.ingest.worker import enqueue, get_worker
from app.query import templates as T
from app.query.compare import compare_protocols
from app.query.engine import run_query

router = APIRouter(prefix="/api", tags=["query"])


# ---------------------------------------------------------------- query
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    strategy: str = Field("bfs", pattern="^(bfs|dfs)$")
    limit: int = Field(25, ge=1, le=60)


class StructuredQueryRequest(BaseModel):
    template: str
    params: dict[str, Any] = {}
    strategy: str = Field("bfs", pattern="^(bfs|dfs)$")
    limit: int = Field(25, ge=1, le=60)


class QueryResponse(BaseModel):
    query_id: str
    question: Optional[str]
    interpreted_query: str
    intent: str
    matched_entities: list[dict]
    retrieved_nodes: list[dict]
    retrieved_relationships: list[dict]
    supporting_claims: list[dict]
    supporting_documents: list[dict]
    evidence_passages: list[dict]
    graph_paths: list[dict]
    traversal: Optional[dict]
    retrieval_method: dict
    relevance_scores: dict[str, float]
    validation_status: str
    validation_issues: list[str]
    conflicts: list[dict]
    unresolved_terms: list[str]
    warnings: list[str]
    lexical_passages: list[dict]
    answer_summary: dict
    latency_ms: float


@router.post("/query", response_model=QueryResponse, summary="Natural-language graph query (GraphRAG)")
def query(req: QueryRequest):
    return run_query(req.question, strategy=req.strategy, limit=req.limit)


@router.post("/query/structured", response_model=QueryResponse, summary="Validated structured graph query (allowlisted template)")
def structured(req: StructuredQueryRequest):
    try:
        T.get(req.template)
    except KeyError as e:
        raise HTTPException(400, str(e))
    for k, v in req.params.items():
        if k in ("rels",) or not isinstance(v, (str, int, float, type(None))):
            raise HTTPException(400, f"parameter '{k}' must be a scalar value")
    return run_query(structured={"template": req.template, "params": req.params}, strategy=req.strategy, limit=req.limit)


@router.get("/query/templates", summary="Allowlisted graph query templates")
def templates():
    return [{"name": k, "description": v["description"], "params": v["params"]} for k, v in T.TEMPLATES.items()]


# ---------------------------------------------------------------- evidence
@router.get("/evidence/search", summary="Lexical (full-text) passage discovery - complementary to graph retrieval")
def evidence_search(q: str = Query(..., min_length=2), doc_id: str = "", section_category: str = "", limit: int = Query(40, le=200)):
    terms = [t for t in re.findall(r"[A-Za-z0-9\-/+.]+", q) if len(t) > 1]
    if not terms:
        return []
    fts = " ".join('"' + t.replace('"', "") + '"' for t in terms)
    where, params = ["chunks_fts MATCH ?"], [fts]
    if doc_id:
        where.append("f.doc_id = ?")
        params.append(doc_id)
    sql = f"""SELECT c.id AS chunk_id, c.doc_id, c.page_start, c.page_end, c.section_title, c.section_category, c.chunk_type,
                     snippet(chunks_fts, 0, '[[', ']]', ' ... ', 40) AS snippet, d.filename, d.title, d.nct_id, bm25(chunks_fts) AS score
              FROM chunks_fts f JOIN chunks c ON c.id = f.chunk_id JOIN documents d ON d.id = c.doc_id
              WHERE {' AND '.join(where)} {"AND c.section_category = ?" if section_category else ""}
              ORDER BY score LIMIT ?"""
    if section_category:
        params.append(section_category)
    try:
        return metadb.q(sql, params + [limit])
    except Exception as e:
        raise HTTPException(400, f"search failed: {e}")


@router.get("/evidence/chunk/{chunk_id}", summary="Evidence chunk with parent section context (parent-child retrieval)")
def evidence_chunk(chunk_id: str, context: int = Query(2, ge=0, le=10)):
    c = metadb.q1("SELECT * FROM chunks WHERE id = ?", (chunk_id,))
    if not c:
        raise HTTPException(404, "Chunk not found")
    c["bbox"] = json.loads(c["bbox"]) if c["bbox"] else []
    sec = metadb.q1("SELECT * FROM sections WHERE id = ?", (c["section_id"],)) if c["section_id"] else None
    around = metadb.q("""SELECT id, chunk_type, page_start, page_end, text FROM chunks WHERE doc_id=? AND section_id IS ? AND ord BETWEEN ? AND ?
                         AND chunk_type NOT IN ('table_row') ORDER BY ord""", (c["doc_id"], c["section_id"], c["ord"] - context, c["ord"] + context))
    parent = metadb.q1("SELECT id, text, page_start FROM chunks WHERE id = ?", (c["parent_chunk_id"],)) if c["parent_chunk_id"] else None
    table = None
    if c["table_id"]:
        table = metadb.q1("SELECT * FROM doc_tables WHERE id = ?", (c["table_id"],))
        if table:
            table["cells"] = json.loads(table["cells"])
    doc = metadb.q1("SELECT id, filename, title, nct_id, version_label, version_date, amendment, page_count FROM documents WHERE id=?", (c["doc_id"],))
    return {"chunk": c, "section": sec, "context": around, "parent": parent, "table": table, "document": doc}


@router.get("/evidence/edge/{edge_id:path}", summary="Provenance of one relationship (claim + all supporting passages)")
def evidence_edge(edge_id: str):
    rows = db.read("""MATCH (a)-[r]->(b) WHERE elementId(r) = $id
                      OPTIONAL MATCH (c:ExtractedClaim {id: r.claim_id})-[s:SUPPORTED_BY]->(ch:EvidenceChunk)
                      RETURN a.id AS source, a.name AS source_name, type(r) AS type, b.id AS target, b.name AS target_name,
                             properties(r) AS props, c.id AS claim_id, c.validation_status AS claim_status,
                             collect(CASE WHEN ch IS NULL THEN NULL ELSE {chunk_id: ch.id, quote: s.quote, page_start: s.page_start,
                                     page_end: s.page_end, section: ch.section_title, doc_id: ch.doc_id, text: ch.text} END) AS evidence""",
                   {"id": edge_id})
    if not rows:
        raise HTTPException(404, "Relationship not found")
    r = rows[0]
    r["evidence"] = [e for e in r["evidence"] if e]
    did = r["props"].get("source_document_id")
    r["document"] = metadb.q1("SELECT id, filename, title, nct_id, version_label, version_date, amendment FROM documents WHERE id=?", (did,)) if did else None
    return r


# ---------------------------------------------------------------- comparison
class CompareRequest(BaseModel):
    protocol_ids: list[str] = Field(..., min_length=2, max_length=4)


@router.post("/compare", summary="Field-by-field protocol comparison with per-protocol evidence")
def compare(req: CompareRequest):
    ids = [p if p.startswith("protocol:") else f"protocol:{p}" for p in req.protocol_ids]
    res = compare_protocols(ids)
    metadb.audit("compare", f"Compared {len(ids)} protocols", None, {"ids": ids})
    return res


# ---------------------------------------------------------------- data quality
@router.get("/quality/summary", summary="Extraction / validation quality indicators")
def quality_summary():
    warn = metadb.q("SELECT severity, code, count(*) n FROM warnings GROUP BY severity, code ORDER BY n DESC")
    docs = metadb.q("""SELECT status, count(*) n, avg(extraction_confidence) conf FROM documents GROUP BY status""")
    kinds = metadb.q("SELECT doc_kind, count(*) n FROM documents GROUP BY doc_kind")
    review = metadb.q("SELECT status, count(*) n FROM resolution_review GROUP BY status")
    sections = metadb.q("SELECT category, count(*) n FROM sections GROUP BY category ORDER BY n DESC")
    validation = db.read("MATCH ()-[r]->() WHERE r.claim_id IS NOT NULL RETURN r.validation_status AS status, count(*) AS n")
    no_criteria = metadb.q("""SELECT d.id, d.filename FROM documents d WHERE d.status='processed' AND d.document_type != 'sap'
                              AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.doc_id=d.id AND s.category IN ('inclusion_criteria','exclusion_criteria','eligibility'))""")
    return {"warnings": warn, "documents": docs, "doc_kinds": kinds, "review": review, "section_categories": sections,
            "relationship_validation": validation, "documents_without_eligibility_section": no_criteria}


@router.get("/quality/warnings", summary="Extraction / validation warnings")
def quality_warnings(severity: str = "", code: str = "", doc_id: str = "", limit: int = Query(300, le=3000)):
    where, params = [], []
    for col, v in (("w.severity", severity), ("w.code", code), ("w.doc_id", doc_id)):
        if v:
            where.append(f"{col} = ?")
            params.append(v)
    return metadb.q(f"""SELECT w.*, d.filename FROM warnings w JOIN documents d ON d.id = w.doc_id
                        {('WHERE ' + ' AND '.join(where)) if where else ''} ORDER BY CASE w.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, w.id DESC LIMIT ?""",
                    params + [limit])


@router.get("/quality/review", summary="Unresolved / ambiguous entity candidates awaiting human review")
def review_items(status: str = "pending", limit: int = 300):
    return metadb.q("""SELECT r.*, d.filename FROM resolution_review r LEFT JOIN documents d ON d.id = r.doc_id
                       WHERE r.status = ? ORDER BY r.score DESC LIMIT ?""", (status, limit))


class ReviewDecision(BaseModel):
    decision: str = Field(..., pattern="^(merge|separate)$")


@router.post("/quality/review/{review_id}", summary="Record a human entity-resolution decision and re-graph affected documents")
def decide(review_id: str, body: ReviewDecision):
    r = metadb.q1("SELECT * FROM resolution_review WHERE id = ?", (review_id,))
    if not r:
        raise HTTPException(404, "Review item not found")
    target = r["candidate_entity_id"] if body.decision == "merge" else None
    with metadb.tx() as c:
        c.execute("INSERT OR REPLACE INTO resolution_decisions(surface_norm, entity_type, decision, target_entity_id, decided_at) VALUES (?,?,?,?,?)",
                  (r["surface_norm"], r["entity_type"], body.decision, target, time.time()))
        c.execute("UPDATE resolution_review SET status=?, decided_at=? WHERE surface_norm=? AND entity_type=?",
                  ("merged" if body.decision == "merge" else "rejected", time.time(), r["surface_norm"], r["entity_type"]))
        if body.decision == "merge":
            c.execute("INSERT OR IGNORE INTO entity_aliases(entity_id, entity_type, name, alias, alias_norm, source) VALUES (?,?,?,?,?,?)",
                      (target, r["entity_type"], r["candidate_name"], r["surface"], r["surface_norm"], "review"))
    docs = [d["doc_id"] for d in metadb.q("SELECT DISTINCT doc_id FROM resolution_review WHERE surface_norm=?", (r["surface_norm"],))]
    jobs = [enqueue(d, kind="regraph") for d in docs if d]
    metadb.audit("resolution.decision", f"'{r['surface']}' -> {body.decision}" + (f" into {r['candidate_name']}" if target else ""),
                 None, {"review_id": review_id, "regraph_docs": docs})
    return {"decision": body.decision, "regraph_jobs": jobs, "documents": docs}


@router.get("/quality/conflicts", summary="Cross-source differences: dose statements and protocol-version differences")
def conflicts(limit: int = 100):
    doses = db.read("""
        MATCH (pr:Protocol)-[:HAS_DOSE_SPECIFICATION]->(ds:DoseSpecification)-[:DOSE_OF]->(d:Drug)
        WITH d, collect(DISTINCT {protocol: pr.id, protocol_name: pr.name, dose: ds.dose_value + ' ' + ds.dose_unit,
                                 frequency: ds.frequency, label: ds.name, page: ds.page}) AS specs
        WITH d, specs, size(apoc.coll.toSet([s IN specs | s.dose])) AS distinct_doses
        WHERE distinct_doses > 1
        RETURN d.id AS drug_id, d.name AS drug, distinct_doses, size(apoc.coll.toSet([s IN specs | s.protocol])) AS protocols, specs[..40] AS specs
        ORDER BY protocols DESC LIMIT $lim""", {"lim": limit}) if _has_apoc() else []
    versions = db.read("""
        MATCH (t:ClinicalTrial)<-[:VERSION_OF]-(p:Protocol)
        WITH t, collect(p {.id, .name, .version_label, .version_date, .amendment, .document_type}) AS ps WHERE size(ps) > 1
        OPTIONAL MATCH (a:Protocol)-[am:AMENDS]->(b:Protocol)-[:VERSION_OF]->(t)
        RETURN t.id AS trial, t.name AS trial_name, ps AS protocols, collect(DISTINCT {newer: a.id, older: b.id, basis: am.basis}) AS amends
        LIMIT $lim""", {"lim": limit})
    endpoint_levels = db.read("""
        MATCH (p:Protocol)-[r1:HAS_PRIMARY_ENDPOINT]->(e:Endpoint)<-[r2:HAS_SECONDARY_ENDPOINT]-(p)
        RETURN p.id AS protocol, p.name AS protocol_name, e.name AS endpoint, r1.source_page_start AS primary_page,
               r2.source_page_start AS secondary_page LIMIT $lim""", {"lim": limit})
    return {"dose_differences": doses, "protocol_versions": versions, "endpoint_level_differences": endpoint_levels,
            "note": "Differences are surfaced for inspection. Each statement keeps its own evidence; none is merged into a universal value."}


def _has_apoc() -> bool:
    try:
        db.read("RETURN apoc.coll.toSet([1,1]) AS x")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- history / audit
@router.get("/history/queries", summary="Query history")
def query_history(limit: int = 100):
    return metadb.q("SELECT id, ts, question, mode, intent, n_nodes, n_edges, validation_status, latency_ms FROM queries ORDER BY ts DESC LIMIT ?", (limit,))


@router.get("/history/queries/{qid}", summary="Stored query: plan, retrieved evidence and validation results")
def query_detail(qid: str):
    r = metadb.q1("SELECT * FROM queries WHERE id = ?", (qid,))
    if not r:
        raise HTTPException(404, "Query not found")
    r["plan"] = json.loads(r["plan"]) if r["plan"] else None
    r["response"] = json.loads(r["response"]) if r["response"] else None
    return r


@router.get("/history/audit", summary="Processing / retrieval audit log")
def audit_log(kind: str = "", limit: int = 200):
    if kind:
        return metadb.q("SELECT * FROM audit WHERE kind LIKE ? ORDER BY ts DESC LIMIT ?", (f"{kind}%", limit))
    return metadb.q("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,))


# ---------------------------------------------------------------- dashboard
@router.get("/stats", summary="Dashboard metrics computed from application data")
def stats():
    d = metadb.q1("""SELECT count(*) total, sum(status='processed') processed, sum(status IN ('queued','processing')) pending,
                            sum(status='processing') processing, sum(status='failed') failed, sum(page_count) pages,
                            avg(CASE WHEN status='processed' THEN extraction_confidence END) mean_conf,
                            sum(doc_kind='scanned') scanned, sum(doc_kind='mixed') mixed FROM documents""")
    chunks = metadb.q1("SELECT count(*) n FROM chunks WHERE chunk_type != 'toc'")["n"]
    tables = metadb.q1("SELECT count(*) n FROM doc_tables")["n"]
    warn = metadb.q1("SELECT sum(severity='error') errors, sum(severity='warning') warnings FROM warnings")
    out: dict[str, Any] = {"documents": d, "evidence_passages": chunks, "tables": tables, "warnings": warn,
                           "worker": get_worker().status()}
    try:
        g = db.read("""
            CALL () { MATCH (n:KG {scope:'canonical'}) RETURN count(n) AS canonical }
            CALL () { MATCH ()-[r]->() WHERE r.claim_id IS NOT NULL RETURN count(r) AS clinical }
            CALL () { MATCH ()-[r]->() RETURN count(r) AS all_rels }
            CALL () { MATCH (t:ClinicalTrial) RETURN count(t) AS trials }
            CALL () { MATCH (p:Protocol) RETURN count(p) AS protocols }
            CALL () { MATCH (x:Drug) RETURN count(x) AS drugs }
            CALL () { MATCH (x:Intervention) RETURN count(x) AS interventions }
            CALL () { MATCH (x) WHERE x:CancerSubtype OR x:Disease RETURN count(x) AS conditions }
            CALL () { MATCH (x:Biomarker) RETURN count(x) AS biomarkers }
            CALL () { MATCH (x:Endpoint) RETURN count(x) AS endpoints }
            CALL () { MATCH (x:AdverseEvent) RETURN count(x) AS adverse_events }
            CALL () { MATCH ()-[r]->() WHERE r.claim_id IS NOT NULL AND r.validation_status = 'validated' RETURN count(r) AS validated }
            RETURN *""")[0]
        out["graph"] = g
        out["graph_status"] = "online"
    except Exception as e:
        out["graph"] = None
        out["graph_status"] = f"unavailable: {type(e).__name__}"
    out["recent_queries"] = metadb.q("SELECT id, ts, question, intent, n_nodes, n_edges, validation_status, latency_ms FROM queries ORDER BY ts DESC LIMIT 8")
    out["recent_activity"] = metadb.q("SELECT ts, kind, doc_id, message FROM audit ORDER BY ts DESC LIMIT 12")
    out["status_by_day"] = metadb.q("""SELECT date(processed_at, 'unixepoch') day, count(*) n FROM documents WHERE processed_at IS NOT NULL
                                       GROUP BY day ORDER BY day""")
    return out
