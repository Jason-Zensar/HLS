"""Convert Neo4j nodes / relationships / paths into JSON for the API."""
from __future__ import annotations

from typing import Any

from app.graph.schema import NODE_GROUP, RELATIONSHIPS, primary_type

NODE_KEEP = {"name", "type", "scope", "resolution_status", "doc_id", "nct_id", "phase", "sponsor", "version_label",
             "version_date", "amendment", "document_type", "title", "filename", "page_count", "text", "number", "page",
             "dose_value", "dose_unit", "frequency", "route", "drug_id", "length_days", "description", "aliases", "kind",
             "class_key", "canonical_source", "candidate_match", "candidate_score", "chunk_id", "page_start", "page_end",
             "section_title", "category", "protocol_id", "predicate", "confidence", "quote", "validation_status"}
EDGE_KEEP = {"claim_id", "relationship_type", "source_document_id", "source_version_id", "source_chunk_id", "source_page_start",
             "source_page_end", "supporting_quote", "source_section", "extraction_method", "extraction_confidence",
             "validation_status", "assertion_type", "evidence_count", "evidence_pages", "protocol_id", "count", "pages",
             "surface_forms", "basis"}


def node_json(n: Any) -> dict:
    labels = sorted(n.labels)
    t = primary_type(labels)
    props = {}
    for k, v in dict(n).items():
        if k in NODE_KEEP:
            if isinstance(v, str) and len(v) > 1200:
                v = v[:1200] + " ..."
            props[k] = v
    return {"id": n["id"], "element_id": n.element_id, "type": t, "labels": [l for l in labels if l != "KG"],
            "name": n.get("name") or n["id"], "group": NODE_GROUP.get(t, "other"), "props": props,
            "scope": n.get("scope")}


def edge_json(r: Any, source: str | None = None, target: str | None = None) -> dict:
    props = {k: v for k, v in dict(r).items() if k.startswith("q_") or k in EDGE_KEEP}
    cat = RELATIONSHIPS.get(r.type, (None, None, "other"))[2]
    s = source or (r.start_node.get("id") if r.start_node is not None else None)
    t = target or (r.end_node.get("id") if r.end_node is not None else None)
    return {"id": r.element_id, "type": r.type, "source": s, "target": t,
            "category": cat, "assertion_type": props.get("assertion_type"), "validation_status": props.get("validation_status"),
            "confidence": props.get("extraction_confidence"), "props": props}


def collect_paths(records: list, nodes: dict, edges: dict, paths_out: list, extra_out: list | None = None) -> None:
    for rec in records:
        for p in rec.get("paths") or []:
            if p is None:
                continue
            pn = [node_json(n) for n in p.nodes]
            pe = [edge_json(r) for r in p.relationships]
            for n in pn:
                nodes.setdefault(n["id"], n)
            for e in pe:
                edges.setdefault(e["id"], e)
            if pe:
                seq = []
                for i, r in enumerate(p.relationships):
                    forward = r.start_node["id"] == pn[i]["id"]
                    seq.append({"edge_id": r.element_id, "type": r.type, "direction": "forward" if forward else "reverse"})
                paths_out.append({"start": pn[0]["id"], "end": pn[-1]["id"], "nodes": [n["id"] for n in pn],
                                  "relationships": seq, "hops": len(pe), "source": "template"})
        if extra_out is not None:
            extra = {k: rec[k] for k in rec.keys() if k != "paths"}
            if extra:
                extra_out.append(extra)
