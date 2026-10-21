"""Graph ingestion (idempotent, per document).

`write_document` first removes everything the document previously contributed (its own nodes
and every relationship whose source_document_id is the document), then writes:
* canonical entities (MERGE - shared across documents) and their terminology edges,
* document-owned nodes (Protocol, criteria, arms, doses, Document, sections, evidence chunks,
  tables, ExtractedClaim nodes),
* one relationship per (predicate, subject, object) claim, carrying full provenance, plus
  ExtractedClaim-[:SUPPORTED_BY]->EvidenceChunk links for every supporting passage,
* aggregated Document-[:MENTIONS]->entity edges.
Re-running it for the same document therefore never duplicates nodes or relationships.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from typing import Any

from app.extraction import lexicon as L
from app.extraction.entities import norm
from app.graph import neo4j_client as db
from app.graph.schema import RELATIONSHIPS, validate_edge

log = logging.getLogger(__name__)
BATCH = 500


def _batches(rows: list, n: int = BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def _label_str(labels: list[str]) -> str:
    safe = [l for l in labels if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", l)]
    return ":".join(["KG", *dict.fromkeys(safe)])


def delete_document(doc_id: str) -> None:
    present = db.write("MATCH (n:KG {doc_id: $d}) RETURN count(n) > 0 AS p", {"d": doc_id})
    if present and not present[0]["p"]:
        return  # nothing from this document is in the graph yet (first ingestion)
    for rel in RELATIONSHIPS:
        db.write(f"MATCH ()-[r:{rel}]->() WHERE r.source_document_id = $d DELETE r", {"d": doc_id})
    while True:
        res = db.write("MATCH (n:KG {doc_id: $d}) WITH n LIMIT 5000 DETACH DELETE n RETURN count(*) AS c", {"d": doc_id})
        if not res or res[0]["c"] == 0:
            break
    cleanup_orphans()


def cleanup_orphans() -> None:
    # canonical nodes no longer connected to any document-derived edge (terminology-only links don't count)
    db.write("""
        MATCH (n:KG) WHERE n.scope = 'canonical' AND NOT n:DrugClass
          AND NOT EXISTS { MATCH (n)-[r]-() WHERE r.source_document_id IS NOT NULL OR type(r) = 'MENTIONS' OR type(r) = 'VERSION_OF' OR type(r) = 'SPONSORED_BY' }
        DETACH DELETE n""")


def _upsert_nodes(nodes: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        groups[_label_str([n["type"], *n.get("labels", [])])].append(n)
    for labels, rows in groups.items():
        for b in _batches(rows):
            db.write(f"""
                UNWIND $rows AS row
                MERGE (n:KG {{id: row.id}})
                SET n:{labels}, n += row.props
                """, {"rows": [{"id": r["id"], "props": r["props"]} for r in b]})


def _create_edges(edges: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        groups[e["type"]].append(e)
    for rtype, rows in groups.items():
        if rtype not in RELATIONSHIPS:
            continue
        for b in _batches(rows):
            db.write(f"""
                UNWIND $rows AS row
                MATCH (a:KG {{id: row.s}}) MATCH (b:KG {{id: row.o}})
                CREATE (a)-[r:{rtype}]->(b) SET r += row.props
                """, {"rows": b})


def _merge_edges(edges: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        groups[e["type"]].append(e)
    for rtype, rows in groups.items():
        for b in _batches(rows):
            db.write(f"""
                UNWIND $rows AS row
                MATCH (a:KG {{id: row.s}}) MATCH (b:KG {{id: row.o}})
                MERGE (a)-[r:{rtype}]->(b) SET r += row.props
                """, {"rows": b})


def concept_node(cid: str) -> dict:
    c = L.BY_ID[cid]
    aliases = sorted({c.name, *c.aliases, *c.cs_aliases})
    props = {"name": c.name, "type": c.type, "scope": "canonical", "name_norm": norm(c.name),
             "aliases": aliases, "aliases_text": " | ".join(aliases), "resolution_status": "resolved",
             "canonical_source": "curated lexicon"}
    for k, v in c.props.items():
        if isinstance(v, (str, int, float, bool)) or (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            props[k] = v
    return {"id": cid, "type": c.type, "labels": c.extra_labels, "props": props}


def terminology_edges(cids: set[str]) -> tuple[list[dict], list[dict]]:
    """Drug -> DrugClass (+ class hierarchy) and regimen -> components. Reference knowledge only."""
    nodes, edges = {}, []
    tprops = {"assertion_type": "terminology", "extraction_method": "curated_lexicon", "validation_status": "reference",
              "relationship_type": None}
    for cid in cids:
        c = L.BY_ID.get(cid)
        if not c:
            continue
        if c.type == "Drug":
            for cls in c.classes:
                chain = cls
                while chain:
                    nodes[chain] = concept_node(chain)
                    parent = L.CLASS_PARENT.get(chain)
                    if parent:
                        nodes[parent] = concept_node(parent)
                        edges.append({"type": "SUBCLASS_OF", "s": chain, "o": parent, "props": {**tprops, "relationship_type": "SUBCLASS_OF"}})
                    chain = parent
                edges.append({"type": "BELONGS_TO_CLASS", "s": cid, "o": cls, "props": {**tprops, "relationship_type": "BELONGS_TO_CLASS"}})
        if c.type == "CombinationTherapy":
            for comp in c.props.get("components", []):
                nodes[comp] = concept_node(comp)
                edges.append({"type": "CONTAINS_DRUG", "s": cid, "o": comp, "props": {**tprops, "relationship_type": "CONTAINS_DRUG"}})
    return list(nodes.values()), edges


def trial_key(doc: dict) -> tuple[str, str, str] | None:
    """Registered-trial identity: NCT number printed in the document, else the sponsor protocol code."""
    if doc.get("nct_id"):
        return f"trial:{doc['nct_id']}", doc["nct_id"], "NCT identifier printed in the document"
    code = (doc.get("sponsor_protocol_code") or "").strip()
    if len(code) >= 4 and re.search(r"\d", code):
        return f"trial:code:{code.upper()}", code, "sponsor protocol code printed in the document (no NCT number found)"
    return None


def write_document(doc: dict, sections: list[dict], chunks: list[dict], tables: list[dict], ext: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    doc_id = doc["id"]
    now = time.time()
    delete_document(doc_id)

    chunk_by_id = {c["id"]: c for c in chunks}
    entities = {e["id"]: e for e in ext["entities"]}
    mention_ids = {m[0] for m in ext["mentions"]}

    # ---------------- nodes
    canonical: list[dict] = []
    for eid in set(entities) | mention_ids:
        if eid in L.BY_ID:
            canonical.append(concept_node(eid))
    for e in entities.values():
        if e["scope"] == "canonical" and e["id"] not in L.BY_ID:
            props = {"name": e["name"], "type": e["type"], "scope": "canonical", "name_norm": norm(e["name"]),
                     "aliases": [e["name"]], "aliases_text": e["name"], "resolution_status": e["resolution_status"],
                     "canonical_source": "document-derived (unresolved)"}
            props.update({k: v for k, v in e["props"].items() if isinstance(v, (str, int, float, bool))})
            canonical.append({"id": e["id"], "type": e["type"], "labels": e.get("labels", []), "props": props})
    term_nodes, term_edges = terminology_edges(set(entities) | mention_ids)
    _upsert_nodes(canonical + term_nodes)
    _merge_edges(term_edges)

    owned: list[dict] = []
    owned.append({"id": f"doc:{doc_id}", "type": "Document", "labels": [], "props": {
        "doc_id": doc_id, "scope": "document", "name": doc["filename"], "title": doc.get("title"), "filename": doc["filename"],
        "page_count": doc.get("page_count"), "sha256": doc["sha256"], "doc_kind": doc.get("doc_kind"),
        "document_type": doc.get("document_type"), "type": "Document"}})
    for e in entities.values():
        if e["scope"] != "document":
            continue
        props = {"name": e["name"], "type": e["type"], "scope": "document", "doc_id": doc_id, "name_norm": norm(e["name"])}
        for k, v in e["props"].items():
            if v is None:
                continue
            props[k] = v if isinstance(v, (str, int, float, bool)) else json.dumps(v)
        owned.append({"id": e["id"], "type": e["type"], "labels": e.get("labels", []), "props": props})

    # sponsor & registered trial (canonical, shared across versions)
    struct_edges: list[dict] = [{"type": "DESCRIBED_IN", "s": f"protocol:{doc_id}", "o": f"doc:{doc_id}",
                                 "props": {"source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "DESCRIBED_IN"}}]
    tkey = trial_key(doc)
    if tkey:
        tid, tname, basis = tkey
        canonical_trial = {"id": tid, "type": "ClinicalTrial", "labels": [], "props": {
            "name": tname, "nct_id": doc.get("nct_id") or "", "sponsor_protocol_code": doc.get("sponsor_protocol_code") or "",
            "identifier_basis": basis, "scope": "canonical", "type": "ClinicalTrial", "name_norm": tname.lower()}}
        _upsert_nodes([canonical_trial])
        struct_edges.append({"type": "VERSION_OF", "s": f"protocol:{doc_id}", "o": tid,
                             "props": {"source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "VERSION_OF",
                                       "basis": basis}})
    if doc.get("sponsor"):
        sid = f"sponsor:{L.slug(doc['sponsor'])[:60]}"
        _upsert_nodes([{"id": sid, "type": "Sponsor", "labels": [], "props": {"name": doc["sponsor"], "scope": "canonical", "type": "Sponsor", "name_norm": norm(doc["sponsor"])}}])
        struct_edges.append({"type": "SPONSORED_BY", "s": f"protocol:{doc_id}", "o": sid,
                             "props": {"source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "SPONSORED_BY"}})

    for s in sections:
        owned.append({"id": s["id"], "type": "DocumentSection", "labels": [], "props": {
            "doc_id": doc_id, "scope": "document", "name": (s["number"] + " " if s["number"] else "") + (s["title"] or "")[:150],
            "title": s["title"], "number": s["number"], "category": s["category"], "level": s["level"],
            "page_start": s["page_start"], "page_end": s["page_end"], "detection": s["detection"], "type": "DocumentSection"}})
        struct_edges.append({"type": "PART_OF", "s": s["id"], "o": s["parent_id"] or f"doc:{doc_id}",
                             "props": {"source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "PART_OF"}})

    # ---------------- claims -> validated edges
    rejected, edges, claim_nodes, support = [], [], [], []
    used_chunks: set[str] = set()
    for cl in ext["claims"]:
        s_ent = entities.get(cl["subject"]) or ({"type": L.BY_ID[cl["subject"]].type} if cl["subject"] in L.BY_ID else None)
        o_ent = entities.get(cl["object"]) or ({"type": L.BY_ID[cl["object"]].type} if cl["object"] in L.BY_ID else None)
        if not s_ent or not o_ent:
            rejected.append({**cl, "reason": "endpoint entity missing"})
            continue
        reason = validate_edge(cl["predicate"], s_ent["type"], o_ent["type"])
        if reason:
            rejected.append({**cl, "reason": reason})
            continue
        evs = [e for e in cl["evidence"] if e["chunk_id"] in chunk_by_id]
        if not evs:
            rejected.append({**cl, "reason": "no supporting evidence chunk"})
            continue
        primary = max(evs, key=lambda e: e["confidence"])
        status = "validated"
        ctext = re.sub(r"\s+", " ", chunk_by_id[primary["chunk_id"]]["text"])
        q = re.sub(r"\s+", " ", primary["quote"]).rstrip(" .")
        if q.endswith("..."):
            q = q[:-3].rstrip()
        if q[:120] not in ctext and q[:120] not in (doc.get("title") or ""):
            status = "quote_not_found"
        if cl["confidence"] < 0.5:
            status = "low_confidence" if status == "validated" else status
        for e in evs:
            used_chunks.add(e["chunk_id"])
        props = {
            "claim_id": cl["id"], "relationship_type": cl["predicate"], "source_document_id": doc_id,
            "source_version_id": doc.get("version_label") or doc.get("version_date"), "source_chunk_id": primary["chunk_id"],
            "source_page_start": primary["page_start"], "source_page_end": primary["page_end"],
            "supporting_quote": primary["quote"], "source_section": primary["section"],
            "extraction_method": cl["method"], "extraction_confidence": cl["confidence"],
            "validation_status": status, "assertion_type": cl["assertion_type"], "created_at": now,
            "evidence_count": cl["evidence_count"], "evidence_pages": sorted({e["page_start"] for e in evs}),
            "protocol_id": f"protocol:{doc_id}",
        }
        for k, v in cl["qualifiers"].items():
            props[f"q_{k}"] = v if isinstance(v, (str, int, float, bool)) else str(v)
        edges.append({"type": cl["predicate"], "s": cl["subject"], "o": cl["object"], "props": props})
        claim_nodes.append({"id": cl["id"], "type": "ExtractedClaim", "labels": [], "props": {
            "doc_id": doc_id, "scope": "document", "type": "ExtractedClaim", "predicate": cl["predicate"],
            "subject_id": cl["subject"], "object_id": cl["object"], "assertion_type": cl["assertion_type"],
            "confidence": cl["confidence"], "extraction_method": cl["method"], "validation_status": status,
            "evidence_count": cl["evidence_count"], "quote": primary["quote"], "page_start": primary["page_start"],
            "page_end": primary["page_end"], "name": f"{cl['predicate']} claim", "qualifiers": json.dumps(cl["qualifiers"])}})
        for e in evs:
            support.append({"type": "SUPPORTED_BY", "s": cl["id"], "o": e["chunk_id"], "props": {
                "quote": e["quote"], "page_start": e["page_start"], "page_end": e["page_end"], "confidence": e["confidence"],
                "source_document_id": doc_id, "relationship_type": "SUPPORTED_BY", "assertion_type": "structural"}})
        support.append({"type": "DERIVED_FROM", "s": cl["id"], "o": f"doc:{doc_id}", "props": {
            "source_document_id": doc_id, "relationship_type": "DERIVED_FROM", "assertion_type": "structural"}})

    # evidence chunks referenced by claims (and their table parents)
    table_ids = set()
    for cid in list(used_chunks):
        c = chunk_by_id[cid]
        if c.get("parent_chunk_id") and c["parent_chunk_id"] in chunk_by_id:
            used_chunks.add(c["parent_chunk_id"])
        if c.get("table_id"):
            table_ids.add(c["table_id"])
    for cid in used_chunks:
        c = chunk_by_id[cid]
        owned.append({"id": cid, "type": "EvidenceChunk", "labels": [], "props": {
            "doc_id": doc_id, "scope": "document", "type": "EvidenceChunk", "name": f"p.{c['page_start']} {c['section_title'][:60]}",
            "text": c["text"][:3000], "page_start": c["page_start"], "page_end": c["page_end"], "chunk_type": c["chunk_type"],
            "section_title": c["section_title"], "section_category": c["section_category"],
            "extraction_method": c["extraction_method"], "extraction_confidence": c["extraction_confidence"],
            "document_version": doc.get("version_label")}})
        if c.get("section_id"):
            struct_edges.append({"type": "PART_OF", "s": cid, "o": c["section_id"], "props": {
                "source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "PART_OF"}})
        if c.get("table_id"):
            struct_edges.append({"type": "DERIVED_FROM", "s": cid, "o": c["table_id"], "props": {
                "source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "DERIVED_FROM"}})
    for t in tables:
        if t["id"] in table_ids:
            owned.append({"id": t["id"], "type": "Table", "labels": [], "props": {
                "doc_id": doc_id, "scope": "document", "type": "Table", "name": (t["title"] or f"Table p.{t['page']}")[:120],
                "page_start": t["page"], "n_rows": t["n_rows"], "n_cols": t["n_cols"]}})
            if t.get("section_id"):
                struct_edges.append({"type": "PART_OF", "s": t["id"], "o": t["section_id"], "props": {
                    "source_document_id": doc_id, "assertion_type": "structural", "relationship_type": "PART_OF"}})

    _upsert_nodes(owned + claim_nodes)
    _create_edges(struct_edges + edges + support)

    # ---------------- mentions (aggregated)
    agg: dict[str, dict] = {}
    for eid, chunk_id, surface, page in ext["mentions"]:
        a = agg.setdefault(eid, {"count": 0, "pages": set(), "surfaces": Counter()})
        a["count"] += 1
        a["pages"].add(page)
        a["surfaces"][surface] += 1
    mrows = [{"type": "MENTIONS", "s": f"doc:{doc_id}", "o": eid, "props": {
        "source_document_id": doc_id, "relationship_type": "MENTIONS", "assertion_type": "mention", "count": a["count"],
        "pages": sorted(a["pages"])[:40], "surface_forms": [s for s, _ in a["surfaces"].most_common(6)],
        "validation_status": "mention_only"}} for eid, a in agg.items()]
    _create_edges(mrows)

    n_edges = len(edges)
    return {"nodes": len(owned) + len(claim_nodes), "canonical_nodes": len(canonical), "relationships": n_edges,
            "rejected": rejected, "mentions": len(mrows), "seconds": round(time.time() - t0, 2),
            "entity_count": len({e["o"] for e in edges} | {e["s"] for e in edges})}


def rebuild_versions(trial_id: str) -> list[str]:
    """Order protocol versions of one trial using explicit version metadata only."""
    nct_id = trial_id
    rows = db.read("""
        MATCH (p:Protocol)-[:VERSION_OF]->(:ClinicalTrial {id: $n})
        RETURN p.id AS id, p.version_date AS vd, p.amendment AS am, p.version_label AS vl, p.document_type AS dt
        """, {"n": nct_id})
    db.write("""MATCH (:Protocol)-[r:AMENDS]->(:Protocol)-[:VERSION_OF]->(:ClinicalTrial {id: $n}) DELETE r""", {"n": nct_id})
    notes = []
    prot = [r for r in rows if (r["dt"] or "protocol") != "sap"]
    if len(prot) < 2:
        return notes

    def key(r):
        am = int(r["am"]) if r["am"] and str(r["am"]).isdigit() else None
        vl = tuple(int(x) for x in r["vl"].split(".")) if r["vl"] and re.fullmatch(r"\d+(\.\d+)*", r["vl"]) else None
        return (r["vd"], am, vl)

    if all(r["vd"] for r in prot):
        ordered, basis = sorted(prot, key=lambda r: r["vd"]), "version date"
    elif all(key(r)[1] is not None for r in prot):
        ordered, basis = sorted(prot, key=lambda r: key(r)[1]), "amendment number"
    elif all(key(r)[2] is not None for r in prot):
        ordered, basis = sorted(prot, key=lambda r: key(r)[2]), "version number"
    else:
        notes.append(f"{nct_id}: {len(prot)} protocol documents but version order is not stated in all of them; no AMENDS edges created")
        return notes
    for older, newer in zip(ordered, ordered[1:]):
        if key(older) == key(newer):
            notes.append(f"{nct_id}: two documents share the same version metadata; order left undetermined")
            continue
        db.write("""MATCH (a:Protocol {id: $new}), (b:Protocol {id: $old})
                    CREATE (a)-[:AMENDS {basis: $basis, assertion_type: 'structural', relationship_type: 'AMENDS',
                                          validation_status: 'derived_from_version_metadata', source_document_id: null}]->(b)""",
                 {"new": newer["id"], "old": older["id"], "basis": basis})
    return notes
