"""Query execution pipeline (GraphRAG).

 1  parse question                      6  execute read-only, timeout, limits
 2  detect intent / entity types        7  collect nodes + relationships (real stored paths)
 3  resolve terms -> canonical nodes    8  fetch supporting claims + evidence passages
 4  pick allowlisted graph patterns     9  rank (confidence x evidence x hop penalty)
 5  parameterised Cypher templates     10  BFS / DFS answer tree + reasoning paths
11  deduplicate nodes, keep distinct assertions   12  validate (Layer 4)
13  evidence-grounded summary (Layer 5)           14  audit log
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.core import metadb
from app.graph import neo4j_client as db
from app.query import answer as answer_mod
from app.query import templates as T
from app.query.linker import Linked, link_entities
from app.query.planner import Plan, Step, plan_query
from app.query.serialize import collect_paths
from app.query.traversal import build_answer_tree

NO_EVIDENCE = "No sufficiently supported evidence was found in the currently indexed protocol documents."
MAX_NODES, MAX_EDGES = 350, 900


def _run_step(step: Step, nodes: dict, edges: dict, paths: list, extras: list, warnings: list) -> None:
    tpl = T.get(step.template)
    params = {"limit": 25, "per": 30, "id": None, "ae": None, **step.params}
    try:
        recs = db.read_records(tpl["cypher"], params)
    except Exception as e:
        warnings.append(f"Template {step.template} failed: {type(e).__name__}: {str(e)[:200]}")
        return
    collect_paths(recs, nodes, edges, paths, extras)


def _constraint_filter(plan: Plan, nodes: dict, edges: dict, paths: list, warnings: list) -> None:
    cons = plan.traversal.get("constraints") or []
    if not cons:
        return
    pids = [n for n, v in nodes.items() if v["type"] == "Protocol"]
    keep = set(pids)
    for cid in cons:
        recs = db.read_records("""
            MATCH (pr:Protocol) WHERE pr.id IN $pids
            MATCH p = (pr)-[r]->(x:KG {id: $cid}) WHERE r.claim_id IS NOT NULL
            RETURN collect(p) AS paths
            UNION
            MATCH (pr:Protocol) WHERE pr.id IN $pids
            MATCH p = (pr)-[:HAS_INCLUSION_CRITERION]->(:EligibilityCriterion)-[r]->(x:KG {id: $cid})
            RETURN collect(p) AS paths""", {"pids": pids, "cid": cid})
        cnodes: dict = {}
        cedges: dict = {}
        cpaths: list = []
        collect_paths(recs, cnodes, cedges, cpaths)
        matched = {p["start"] for p in cpaths}
        keep &= matched
        nodes.update(cnodes)
        edges.update(cedges)
        paths.extend(cpaths)
    drop = set(pids) - keep
    if drop:
        for p in list(paths):
            if set(p["nodes"]) & drop:
                paths.remove(p)
        used_nodes = {n for p in paths for n in p["nodes"]}
        used_edges = {r["edge_id"] for p in paths for r in p["relationships"]}
        for n in list(nodes):
            if n not in used_nodes:
                del nodes[n]
        for e in list(edges):
            if e not in used_edges:
                del edges[e]
    if not keep:
        warnings.append("No protocol satisfies all requested constraints.")


def _fetch_evidence(claim_ids: list[str]) -> dict[str, dict]:
    if not claim_ids:
        return {}
    rows = db.read("""
        MATCH (c:ExtractedClaim) WHERE c.id IN $ids
        OPTIONAL MATCH (c)-[s:SUPPORTED_BY]->(ch:EvidenceChunk)
        RETURN c.id AS claim_id, c.predicate AS predicate, c.subject_id AS subject_id, c.object_id AS object_id,
               c.doc_id AS doc_id, c.confidence AS confidence, c.assertion_type AS assertion_type,
               c.validation_status AS validation_status, c.evidence_count AS evidence_count, c.qualifiers AS qualifiers,
               collect(CASE WHEN ch IS NULL THEN NULL ELSE {chunk_id: ch.id, doc_id: ch.doc_id, quote: s.quote,
                       page_start: s.page_start, page_end: s.page_end, section: ch.section_title,
                       chunk_type: ch.chunk_type} END) AS evidence""", {"ids": claim_ids})
    return {r["claim_id"]: r for r in rows}


def support_level(claim: dict | None, edge: dict) -> str:
    at = edge.get("assertion_type")
    if edge["category"] == "terminology":
        return "reference_terminology"
    if edge["category"] == "mention":
        return "mention_only"
    if edge["category"] == "structural":
        return "document_structure"
    if at == "background_statement":
        return "background_literature"
    if not claim:
        return "uncertain"
    if claim["validation_status"] in ("quote_not_found", "low_confidence"):
        return "uncertain"
    if at == "normalized":
        return "inferred_from_validated_graph_path"
    if (claim.get("evidence_count") or 0) >= 2 and len([e for e in claim["evidence"] if e]) >= 2:
        return "supported_by_multiple_passages"
    return "supported_by_one_passage"


def _validate(nodes: dict, edges: dict, paths: list, claims: dict[str, dict]) -> tuple[str, list[str], dict[str, str]]:
    issues: list[str] = []
    per_edge: dict[str, str] = {}
    # (a) every returned relationship still exists in the store
    ids = list(edges)
    found = set()
    for i in range(0, len(ids), 500):
        rows = db.read("MATCH ()-[r]->() WHERE elementId(r) IN $ids RETURN elementId(r) AS id", {"ids": ids[i:i + 500]})
        found |= {r["id"] for r in rows}
    for eid, e in edges.items():
        status = "ok"
        if eid not in found:
            status = "edge_not_found"
        elif e["category"] == "clinical":
            p = e["props"]
            if not (p.get("claim_id") and p.get("source_document_id") and p.get("supporting_quote") and p.get("source_page_start")):
                status = "missing_provenance"
            else:
                c = claims.get(p["claim_id"])
                if not c:
                    status = "claim_missing"
                elif any(ev and ev["doc_id"] != p["source_document_id"] for ev in c["evidence"]):
                    status = "evidence_document_mismatch"
                elif p.get("validation_status") not in ("validated",):
                    status = p.get("validation_status") or "unvalidated"
        per_edge[eid] = status
        if status not in ("ok", "low_confidence"):
            issues.append(f"{e['type']} {e['source']} -> {e['target']}: {status}")
    # (b) every path is a chain of returned (stored) relationships between returned nodes
    for p in paths:
        for r in p["relationships"]:
            if r["edge_id"] not in edges:
                issues.append(f"path {p['start']} -> {p['end']} references an unknown relationship")
        for n in p["nodes"]:
            if n not in nodes:
                issues.append(f"path {p['start']} -> {p['end']} references an unknown node")
    if not edges:
        return "no_results", issues, per_edge
    bad = sum(1 for s in per_edge.values() if s not in ("ok", "low_confidence"))
    return ("verified" if bad == 0 else "verified_with_warnings"), issues[:50], per_edge


def _conflicts(plan: Plan, nodes: dict, edges: dict) -> list[dict]:
    """Different protocol-specific values for the same entity are surfaced, never merged."""
    out = []
    doses = [n for n in nodes.values() if n["type"] == "DoseSpecification"]
    if doses:
        by_drug: dict[str, list] = defaultdict(list)
        for d in doses:
            by_drug[d["props"].get("drug_id", "")].append(d)
        for drug, ds in by_drug.items():
            vals = defaultdict(list)
            for d in ds:
                key = f"{d['props'].get('dose_value')} {d['props'].get('dose_unit')} {d['props'].get('frequency') or ''}".strip()
                vals[key].append(d["props"].get("protocol_id"))
            if len(vals) > 1:
                prot = defaultdict(set)
                for k, ps in vals.items():
                    for p in ps:
                        prot[p].add(k)
                within = {p: sorted(v) for p, v in prot.items() if len(v) > 1}
                out.append({"kind": "dose_differs", "entity": drug,
                            "message": f"{len(vals)} distinct dose/schedule statements across {len(prot)} protocol(s)",
                            "values": {k: sorted(set(v)) for k, v in vals.items()},
                            "within_protocol": within,
                            "note": "Different protocols may legitimately use different doses (arms, dose levels, reductions). "
                                    "Each statement keeps its own evidence; none is treated as the universal value."})
    # same protocol stating one endpoint at two levels
    lvl = defaultdict(set)
    for e in edges.values():
        if e["type"] in ("HAS_PRIMARY_ENDPOINT", "HAS_SECONDARY_ENDPOINT", "HAS_EXPLORATORY_ENDPOINT"):
            lvl[(e["source"], e["target"])].add(e["type"])
    for (p, ep), types in lvl.items():
        if len(types) > 1:
            out.append({"kind": "endpoint_level_differs", "entity": ep, "protocol": p,
                        "message": f"{nodes.get(ep, {}).get('name', ep)} is described with more than one level ({', '.join(sorted(types))}) "
                                   f"in the same protocol - often different populations or analyses; inspect the evidence.",
                        "values": sorted(types)})
    return out


def run_query(question: str | None = None, *, structured: dict | None = None, strategy: str = "bfs",
              limit: int = 25, record: bool = True) -> dict[str, Any]:
    t0 = time.time()
    s = get_settings()
    qid = "q_" + uuid.uuid4().hex[:12]
    warnings: list[str] = []
    limit = max(1, min(limit, 60))

    if structured:
        # validated structured query: template must be allowlisted; parameters are typed values only
        tname = structured.get("template")
        T.get(tname)
        params = {k: v for k, v in (structured.get("params") or {}).items() if isinstance(v, (str, int, float, list, type(None)))}
        anchors = []
        for key in ("id", "a", "b"):
            if isinstance(params.get(key), str):
                rows = db.read("MATCH (n:KG {id: $id}) RETURN n.id AS id, n.name AS name, labels(n) AS labels", {"id": params[key]})
                if rows:
                    from app.graph.schema import primary_type
                    anchors.append(Linked(rows[0]["id"], rows[0]["name"], primary_type(rows[0]["labels"]), params[key], "structured"))
        from app.query.planner import PATH_RELS, OVERVIEW_RELS, SIMILAR_RELS, SHARED_RELS
        rel_defaults = {"path_between": PATH_RELS, "protocol_overview": OVERVIEW_RELS, "similar_protocols": SIMILAR_RELS,
                        "shared_with_protocol": SHARED_RELS, "entity_neighborhood": PATH_RELS}
        if tname in rel_defaults and "rels" not in params:
            params["rels"] = rel_defaults[tname]
        plan = Plan("structured", f"Structured query: {tname}", anchors,
                    steps=[Step(tname, {"limit": limit, "per": 30, **params}, T.TEMPLATES[tname]["description"])],
                    traversal={"strategy": strategy, "max_depth": 4}, answer_types=["Protocol"])
        unresolved: list[str] = []
        question = question or f"[structured] {tname} {json.dumps(params)[:200]}"
    else:
        anchors, unresolved = link_entities(question or "")
        plan = plan_query(question or "", anchors, limit=limit, strategy=strategy)

    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    paths: list[dict] = []
    extras: list[dict] = []
    for step in plan.steps:
        _run_step(step, nodes, edges, paths, extras, warnings)
    if plan.steps:
        _constraint_filter(plan, nodes, edges, paths, warnings)

    # size limits (server-side) - keep the strongest relationships
    if len(edges) > MAX_EDGES:
        keep = sorted(edges.values(), key=lambda e: -(e.get("confidence") or 0.5))[:MAX_EDGES]
        edges = {e["id"]: e for e in keep}
        warnings.append(f"Result truncated to {MAX_EDGES} relationships (strongest evidence kept).")
        paths = [p for p in paths if all(r["edge_id"] in edges for r in p["relationships"])]
        used = {e["source"] for e in edges.values()} | {e["target"] for e in edges.values()}
        nodes = {k: v for k, v in nodes.items() if k in used}

    claim_ids = sorted({e["props"]["claim_id"] for e in edges.values() if e["props"].get("claim_id")})
    claims = _fetch_evidence(claim_ids)
    validation_status, issues, per_edge = _validate(nodes, edges, paths, claims)
    for eid, st in per_edge.items():
        edges[eid]["validation_check"] = st
        c = claims.get(edges[eid]["props"].get("claim_id"))
        edges[eid]["support_level"] = support_level(c, edges[eid])

    # ranking: node relevance from incident clinical edges
    relevance: dict[str, float] = defaultdict(float)
    for e in edges.values():
        conf = e.get("confidence") or (0.5 if e["category"] != "clinical" else 0.6)
        ev = e["props"].get("evidence_count") or 1
        sc = conf * (1 + math.log1p(ev) / 3)
        if e.get("validation_check") not in ("ok", "low_confidence"):
            sc *= 0.3
        relevance[e["source"]] = max(relevance[e["source"]], sc)
        relevance[e["target"]] = max(relevance[e["target"]], sc)
    for p in paths:
        sc = 1.0
        for r in p["relationships"]:
            e = edges.get(r["edge_id"])
            sc *= (e.get("confidence") or 0.6) if e else 0.1
        p["score"] = round(sc * 0.92 ** (p["hops"] - 1), 4)
    # deduplicate identical paths (same relationship sequence)
    seen, uniq = set(), []
    for p in sorted(paths, key=lambda p: -p["score"]):
        k = tuple(r["edge_id"] for r in p["relationships"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    paths = uniq

    answer_ids = {n for n, v in nodes.items() if v["type"] in plan.answer_types or set(v["labels"]) & set(plan.answer_types)}
    if not answer_ids:
        answer_ids = {p["end"] for p in paths}
    roots = [a.id for a in plan.anchors if a.id in nodes]
    tree = build_answer_tree(nodes, list(edges.values()), roots, answer_ids, strategy=strategy,
                             max_depth=plan.traversal.get("max_depth", 4) + 2) if nodes else None

    conflicts = _conflicts(plan, nodes, edges)
    evidence_passages, supporting_docs = _evidence_view(edges, claims, nodes)
    lexical = _lexical_discovery(plan, nodes) if plan.anchors else []

    response = {
        "query_id": qid, "question": question, "interpreted_query": plan.interpreted, "intent": plan.intent,
        "matched_entities": [{"id": a.id, "name": a.name, "type": a.type, "surface": a.surface, "method": a.method} for a in plan.anchors],
        "retrieved_nodes": list(nodes.values())[:MAX_NODES],
        "retrieved_relationships": list(edges.values()),
        "supporting_claims": [_claim_view(c) for c in claims.values()],
        "supporting_documents": supporting_docs,
        "evidence_passages": evidence_passages,
        "graph_paths": paths[:200],
        "traversal": tree,
        "retrieval_method": {"primary": "graph (allowlisted Cypher templates, read-only)",
                             "templates": [{"name": st.template, "purpose": st.purpose, "params": {k: v for k, v in st.params.items() if k != "rels"}} for st in plan.steps],
                             "traversal": f"{strategy.upper()} spanning tree over retrieved subgraph",
                             "complementary": "lexical full-text passage discovery (shown separately; never creates relationships)" if lexical else None},
        "relevance_scores": {k: round(v, 4) for k, v in sorted(relevance.items(), key=lambda x: -x[1])[:150]},
        "validation_status": validation_status, "validation_issues": issues,
        "conflicts": conflicts, "unresolved_terms": unresolved, "warnings": warnings + plan.notes,
        "lexical_passages": lexical,
    }
    response["answer_summary"] = answer_mod.summarize(plan, response, NO_EVIDENCE)
    response["latency_ms"] = round((time.time() - t0) * 1000, 1)
    if record:
        metadb.execute("""INSERT INTO queries(id, ts, question, mode, intent, plan, n_nodes, n_edges, validation_status, latency_ms, response)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (qid, time.time(), question, "structured" if structured else "natural", plan.intent,
                        json.dumps({"interpreted": plan.interpreted, "steps": response["retrieval_method"]["templates"],
                                    "anchors": response["matched_entities"], "unresolved": unresolved, "strategy": strategy}),
                        len(nodes), len(edges), validation_status, response["latency_ms"],
                        json.dumps(response, default=str)[:1_500_000]))
    return response


def _claim_view(c: dict) -> dict:
    return {"claim_id": c["claim_id"], "predicate": c["predicate"], "subject_id": c["subject_id"], "object_id": c["object_id"],
            "doc_id": c["doc_id"], "confidence": c["confidence"], "assertion_type": c["assertion_type"],
            "validation_status": c["validation_status"], "evidence_count": c["evidence_count"],
            "qualifiers": json.loads(c["qualifiers"]) if c.get("qualifiers") else {},
            "evidence": [e for e in c["evidence"] if e]}


def _evidence_view(edges: dict, claims: dict, nodes: dict) -> tuple[list[dict], list[dict]]:
    doc_ids = {e["props"].get("source_document_id") for e in edges.values() if e["props"].get("source_document_id")}
    doc_ids |= {n["props"].get("doc_id") for n in nodes.values() if n["type"] == "Protocol" and n["props"].get("doc_id")}
    docs = {}
    if doc_ids:
        marks = ",".join("?" * len(doc_ids))
        for d in metadb.q(f"SELECT id, filename, title, nct_id, version_label, version_date, amendment, document_type, page_count, phase, sponsor "
                          f"FROM documents WHERE id IN ({marks})", list(doc_ids)):
            docs[d["id"]] = d
    passages = []
    for e in edges.values():
        if e["category"] != "clinical":
            continue
        c = claims.get(e["props"].get("claim_id"))
        if not c:
            continue
        for ev in [x for x in c["evidence"] if x][:3]:
            d = docs.get(ev["doc_id"], {})
            passages.append({
                "edge_id": e["id"], "claim_id": c["claim_id"], "relationship": e["type"],
                "subject": nodes.get(e["source"], {}).get("name", e["source"]), "object": nodes.get(e["target"], {}).get("name", e["target"]),
                "subject_id": e["source"], "object_id": e["target"],
                "doc_id": ev["doc_id"], "document_title": d.get("title"), "filename": d.get("filename"), "nct_id": d.get("nct_id"),
                "version": d.get("version_label") or d.get("version_date"), "amendment": d.get("amendment"),
                "page_start": ev["page_start"], "page_end": ev["page_end"], "section": ev["section"], "chunk_id": ev["chunk_id"],
                "quote": ev["quote"], "support_level": e.get("support_level"), "validation_status": c["validation_status"],
                "assertion_type": c["assertion_type"], "confidence": c["confidence"]})
    passages.sort(key=lambda p: (-(p["confidence"] or 0), p["doc_id"], p["page_start"]))
    return passages[:250], list(docs.values())


def _lexical_discovery(plan: Plan, nodes: dict) -> list[dict]:
    """Complementary lexical discovery inside the documents already returned by the graph."""
    doc_ids = list({n["props"].get("doc_id") for n in nodes.values() if n["type"] == "Protocol" and n["props"].get("doc_id")})[:40]
    if not doc_ids:
        return []
    ent_ids = [a.id for a in plan.anchors][:3]
    marks = ",".join("?" * len(doc_ids))
    em = ",".join("?" * len(ent_ids))
    rows = metadb.q(f"""SELECT m.entity_id, m.surface, c.id AS chunk_id, c.doc_id, c.page_start, c.page_end, c.section_title,
                               c.section_category, substr(c.text, 1, 600) AS text, d.filename, d.title
                        FROM mentions m JOIN chunks c ON c.id = m.chunk_id JOIN documents d ON d.id = c.doc_id
                        WHERE m.entity_id IN ({em}) AND m.doc_id IN ({marks})
                        GROUP BY c.id ORDER BY c.doc_id, c.page_start LIMIT 300""", ent_ids + doc_ids)
    per_doc: dict[str, int] = defaultdict(int)
    out = []
    for r in rows:
        if per_doc[r["doc_id"]] >= 3:
            continue
        per_doc[r["doc_id"]] += 1
        out.append({**r, "retrieval": "lexical mention (no relationship implied)"})
    return out[:60]
