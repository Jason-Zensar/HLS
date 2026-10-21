"""Graph endpoints: statistics, schema, overview, entity search/detail, neighbourhoods, traversal, paths."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import metadb
from app.graph import neo4j_client as db
from app.graph.schema import EXPLORABLE, NODE_GROUP, NODE_TYPES, RELATIONSHIPS
from app.query.planner import PATH_RELS
from app.query.serialize import edge_json, node_json
from app.query.traversal import expand

router = APIRouter(prefix="/api/graph", tags=["graph"])
entities_router = APIRouter(prefix="/api/entities", tags=["graph"])

HIDDEN = ["ExtractedClaim", "EvidenceChunk", "DocumentSection", "Table"]


@router.get("/schema", summary="Node types, relationship types and visual groups")
def schema():
    return {"node_types": sorted(NODE_TYPES), "groups": NODE_GROUP,
            "relationships": {k: {"subjects": sorted(v[0]), "objects": sorted(v[1]), "category": v[2], "description": v[3]}
                              for k, v in RELATIONSHIPS.items()}}


@router.get("/stats", summary="Graph statistics computed from Neo4j")
def stats():
    labels = db.read("""MATCH (n:KG) UNWIND labels(n) AS l WITH l WHERE l <> 'KG' RETURN l AS label, count(*) AS n ORDER BY n DESC""")
    rels = db.read("""MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC""")
    canon = db.read("""MATCH (n:KG {scope: 'canonical'}) RETURN count(n) AS n""")[0]["n"]
    clinical = sum(r["n"] for r in rels if RELATIONSHIPS.get(r["type"], (0, 0, ""))[2] == "clinical")
    vs = db.read("""MATCH ()-[r]->() WHERE r.claim_id IS NOT NULL RETURN r.validation_status AS s, count(*) AS n""")
    unresolved = db.read("""MATCH (n:KG) WHERE n.resolution_status IN ['unresolved','ambiguous'] RETURN n.resolution_status AS s, count(*) AS n""")
    return {"labels": labels, "relationships": rels, "canonical_entities": canon, "clinical_relationships": clinical,
            "validation": vs, "unresolved_entities": unresolved}


@router.get("/overview", summary="Aggregated overview graph: highest-degree canonical entities and protocols")
def overview(types: str = "Drug,CancerSubtype,Biomarker,Endpoint,Protocol,DrugClass", limit: int = Query(140, le=400),
             rels: str = "", doc_id: str = "", phase: str = ""):
    tlist = [t for t in types.split(",") if t in NODE_TYPES]
    rlist = [r for r in rels.split(",") if r in RELATIONSHIPS] or sorted(EXPLORABLE - {"PART_OF", "DESCRIBED_IN", "SUPPORTED_BY", "DERIVED_FROM", "VERSION_OF", "SPONSORED_BY", "AMENDS"})
    cond = []
    params = {"types": tlist, "rels": rlist, "lim": limit, "doc": doc_id or None, "phase": phase or None}
    recs = db.read_records("""
        MATCH (n:KG) WHERE any(l IN labels(n) WHERE l IN $types)
          AND ($doc IS NULL OR n.doc_id = $doc OR EXISTS { MATCH (n)<-[r]-(:Protocol {doc_id: $doc}) WHERE r.claim_id IS NOT NULL })
          AND ($phase IS NULL OR NOT n:Protocol OR n.phase = $phase)
        WITH n, COUNT { (n)-[r]-() WHERE type(r) IN $rels } AS deg
        WHERE deg > 0
        WITH n, deg ORDER BY deg DESC LIMIT $lim
        RETURN n, deg""", params)
    nodes = {}
    for r in recs:
        nj = node_json(r["n"])
        nj["degree"] = r["deg"]
        nodes[nj["id"]] = nj
    ids = list(nodes)
    erecs = db.read_records("""
        MATCH (a:KG)-[r]->(b:KG) WHERE a.id IN $ids AND b.id IN $ids AND type(r) IN $rels
        WITH a, b, type(r) AS t, collect(r) AS rs
        RETURN rs[0] AS r, a.id AS s, b.id AS o, size(rs) AS multiplicity LIMIT 3000""", {"ids": ids, "rels": rlist})
    edges = []
    for r in erecs:
        e = edge_json(r["r"], r["s"], r["o"])
        e["multiplicity"] = r["multiplicity"]
        edges.append(e)
    return {"nodes": list(nodes.values()), "edges": edges, "aggregated": True,
            "note": "Overview shows the highest-degree entities; parallel protocol-specific edges are aggregated (multiplicity)."}


class TraverseRequest(BaseModel):
    seeds: list[str] = Field(..., min_length=1, max_length=10)
    strategy: str = Field("bfs", pattern="^(bfs|dfs)$")
    max_depth: int = Field(2, ge=1, le=5)
    relationship_types: list[str] = []
    max_nodes: int = Field(80, ge=5, le=300)
    fanout: int = Field(12, ge=1, le=50)


@router.post("/traverse", summary="Server-side BFS / DFS expansion from seed nodes (read-only)")
def traverse(req: TraverseRequest):
    rels = [r for r in req.relationship_types if r in RELATIONSHIPS] or PATH_RELS
    return expand(req.seeds, req.strategy, req.max_depth, rels, req.max_nodes, req.fanout)


@router.get("/neighborhood/{node_id:path}", summary="Neighbourhood of a node (lazy expansion)")
def neighborhood(node_id: str, depth: int = Query(1, ge=1, le=3), limit: int = Query(60, le=300), rels: str = ""):
    rlist = [r for r in rels.split(",") if r in RELATIONSHIPS] or PATH_RELS
    return expand([node_id], "bfs", depth, rlist, max_nodes=limit, fanout=min(limit, 40))


@router.get("/paths", summary="Shortest validated paths between two nodes")
def paths(a: str, b: str, max_hops: int = Query(5, ge=1, le=6), limit: int = Query(10, le=30)):
    from app.query.engine import run_query
    return run_query(structured={"template": "path_between", "params": {"a": a, "b": b}}, limit=limit)


@entities_router.get("/search", summary="Search canonical entities and aliases")
def search(q: str = Query(..., min_length=1), type: str = "", limit: int = Query(25, le=100)):
    qq = " ".join(f"{w}*" if len(w) > 2 else w for w in q.replace('"', " ").split() if w)
    rows = []
    try:
        rows = db.read("""CALL db.index.fulltext.queryNodes('kg_names', $q) YIELD node, score
                          WHERE NOT any(l IN labels(node) WHERE l IN $hidden) AND ($type = '' OR $type IN labels(node))
                          RETURN node.id AS id, node.name AS name, labels(node) AS labels, node.scope AS scope,
                                 node.resolution_status AS resolution_status, score,
                                 COUNT { (node)--() } AS degree
                          ORDER BY score DESC LIMIT $lim""", {"q": qq, "hidden": HIDDEN, "type": type, "lim": limit})
    except Exception:
        pass
    if not rows:
        rows = db.read("""MATCH (node:KG) WHERE toLower(node.name) CONTAINS toLower($q)
                            AND NOT any(l IN labels(node) WHERE l IN $hidden) AND ($type = '' OR $type IN labels(node))
                          RETURN node.id AS id, node.name AS name, labels(node) AS labels, node.scope AS scope,
                                 node.resolution_status AS resolution_status, 1.0 AS score, COUNT { (node)--() } AS degree
                          ORDER BY degree DESC LIMIT $lim""", {"q": q, "hidden": HIDDEN, "type": type, "lim": limit})
    from app.graph.schema import primary_type
    for r in rows:
        r["type"] = primary_type(r["labels"])
        r["group"] = NODE_GROUP.get(r["type"], "other")
    return rows


@entities_router.get("/{node_id:path}", summary="Entity detail: aliases, mentions, protocols, claims, resolution status")
def entity(node_id: str):
    recs = db.read_records("MATCH (n:KG {id: $id}) RETURN n", {"id": node_id})
    if not recs:
        raise HTTPException(404, "Entity not found")
    n = node_json(recs[0]["n"])
    raw = dict(recs[0]["n"])
    n["aliases"] = raw.get("aliases") or []
    conn = db.read("""MATCH (n:KG {id: $id})-[r]-(m:KG) WHERE NOT m:ExtractedClaim AND NOT m:EvidenceChunk AND NOT m:DocumentSection
                      RETURN type(r) AS type, startNode(r) = n AS outgoing, labels(m) AS labels, count(*) AS n
                      ORDER BY n DESC""", {"id": node_id})
    protocols = db.read("""MATCH (n:KG {id: $id})-[r]-(p:Protocol) WHERE r.claim_id IS NOT NULL OR type(r) IN ['VERSION_OF','SPONSORED_BY']
                           RETURN p.id AS id, p.name AS name, p.doc_id AS doc_id, p.nct_id AS nct_id, collect(DISTINCT type(r)) AS relationships,
                                  max(r.extraction_confidence) AS confidence, collect(DISTINCT r.source_page_start)[..10] AS pages
                           ORDER BY confidence DESC LIMIT 200""", {"id": node_id})
    claims = db.read("""MATCH (n:KG {id: $id})-[r]-(m) WHERE r.claim_id IS NOT NULL
                        RETURN r.claim_id AS claim_id, type(r) AS predicate, startNode(r).name AS subject, endNode(r).name AS object,
                               r.source_document_id AS doc_id, r.source_page_start AS page, r.supporting_quote AS quote,
                               r.extraction_confidence AS confidence, r.validation_status AS validation_status, r.assertion_type AS assertion_type,
                               r.extraction_method AS method, elementId(r) AS edge_id
                        ORDER BY confidence DESC LIMIT 80""", {"id": node_id})
    mentions = metadb.q("""SELECT m.doc_id, d.filename, d.title, count(*) AS mentions, group_concat(DISTINCT m.surface) AS surfaces,
                                  min(m.page) AS first_page FROM mentions m JOIN documents d ON d.id=m.doc_id WHERE m.entity_id=?
                           GROUP BY m.doc_id ORDER BY mentions DESC LIMIT 200""", (node_id,))
    doc_aliases = metadb.q("SELECT alias, source FROM entity_aliases WHERE entity_id=? AND source != 'lexicon'", (node_id,))
    review = metadb.q("SELECT id, surface, candidate_name, score, status, reason FROM resolution_review WHERE provisional_entity_id=? OR candidate_entity_id=?",
                      (node_id, node_id))
    return {**n, "connections": conn, "protocols": protocols, "claims": claims, "mentions_by_document": mentions,
            "document_aliases": doc_aliases, "resolution_reviews": review}
