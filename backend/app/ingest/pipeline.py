"""Ingestion pipeline: registration and the per-document stages.

Stages and checkpoints (documents.stage records the last completed one):
  registered -> extracted -> analyzed -> stored -> graphed -> done
`analyze_document` (CPU heavy: extraction, structure, chunking, entity / claim extraction) runs in a
worker process and writes gzip JSON artifacts. `persist_document` (SQLite + Neo4j writes) runs in
the single writer thread. A retry resumes from the last completed stage using the artifacts.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

import pymupdf

from app.config import get_settings
from app.core import metadb
from app.extraction import lexicon as L
from app.extraction.entities import Matcher, base_matcher, extract_metadata, learn_doc_abbreviations, norm
from app.extraction.providers import get_extraction_provider
from app.ingest.chunker import build_chunks
from app.ingest.pdf_extract import extract_pdf
from app.ingest.structure import detect_structure
from app.resolution.resolver import resolve_candidates

log = logging.getLogger(__name__)
STAGES = ["registered", "extracted", "analyzed", "stored", "graphed", "done"]


class DuplicateDocument(Exception):
    def __init__(self, existing_id: str):
        super().__init__(existing_id)
        self.existing_id = existing_id


# ---------------------------------------------------------------------------
# Stage 1: registration
# ---------------------------------------------------------------------------
def register_pdf(data: bytes, filename: str, source: str = "upload") -> dict:
    s = get_settings()
    safe_name = Path(filename).name[:200] or "document.pdf"
    if not data.startswith(b"%PDF"):
        raise ValueError("File is not a PDF (missing %PDF header)")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ValueError(f"File exceeds {s.max_upload_mb} MB")
    sha = hashlib.sha256(data).hexdigest()
    existing = metadb.q1("SELECT id FROM documents WHERE sha256 = ?", (sha,))
    if existing:
        raise DuplicateDocument(existing["id"])
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise ValueError(f"PDF could not be opened (corrupt?): {e}") from e
    if doc.needs_pass:
        raise ValueError("PDF is encrypted / password protected")
    pages = len(doc)
    doc.close()
    doc_id = "d" + sha[:12]
    stored = f"{doc_id}.pdf"
    (s.pdf_dir / stored).write_bytes(data)
    now = time.time()
    with metadb.tx() as c:
        c.execute("""INSERT INTO documents(id, filename, sha256, size_bytes, page_count, status, stage, uploaded_at, stored_name, source)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (doc_id, safe_name, sha, len(data), pages, "queued", "registered", now, stored, source))
        c.execute("INSERT INTO jobs(id, doc_id, kind, status, stage, attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                  (metadb.new_id("job"), doc_id, "ingest", "queued", "registered", 0, now, now))
    metadb.audit("document.registered", f"{safe_name} registered ({pages} pages)", doc_id, {"sha256": sha, "source": source})
    return {"id": doc_id, "filename": safe_name, "page_count": pages, "status": "queued"}


def artifact_path(doc_id: str, name: str) -> Path:
    p = get_settings().artifact_dir / doc_id
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{name}.json.gz"


def save_artifact(doc_id: str, name: str, obj: Any) -> None:
    tmp = artifact_path(doc_id, name).with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    tmp.replace(artifact_path(doc_id, name))


def load_artifact(doc_id: str, name: str) -> Any | None:
    p = artifact_path(doc_id, name)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Stages 2-5 (worker process)
# ---------------------------------------------------------------------------
def analyze_document(doc_id: str, pdf_path: str, filename: str, resume_from: str) -> dict:
    s = get_settings()
    t0 = time.time()
    extraction = load_artifact(doc_id, "extraction")  # checkpoint from an earlier attempt, if any
    if extraction is None:
        extraction = extract_pdf(pdf_path, ocr_enabled=s.ocr_enabled, min_chars=s.ocr_min_chars_per_page,
                                 tables=s.table_detection)
        save_artifact(doc_id, "extraction", extraction)
    t_extract = time.time() - t0

    structure = detect_structure(doc_id, extraction)
    meta = extract_metadata(extraction, [], filename)
    if meta["document_type"] == "protocol" and any(
            re.match(r"statistical analysis plan", sec["title"] or "", re.I) and sec["page_start"] > 10 and sec["level"] <= 1
            for sec in structure["sections"]):
        meta["document_type"] = "protocol+sap"
    version = meta.get("version_label") or meta.get("version_date")
    cres = build_chunks(doc_id, extraction, structure, version)
    chunks, tables = cres["chunks"], cres["tables"]

    texts = [c["text"] for c in chunks if c["chunk_type"] != "toc"]
    abbrevs = learn_doc_abbreviations(texts[:1500], base_matcher())
    matcher = Matcher(extra_cs=abbrevs) if abbrevs else base_matcher()
    provider = get_extraction_provider()
    ext = provider.extract(doc_id, chunks, meta, matcher)

    warnings = [dict(w, stage="extraction") for w in extraction["warnings"]]
    cats = {sec["category"] for sec in structure["sections"]}
    if not ({"inclusion_criteria", "exclusion_criteria", "eligibility"} & cats) and meta["document_type"] != "sap":
        warnings.append({"page": None, "severity": "warning", "code": "eligibility_not_found", "stage": "structure",
                         "message": "No eligibility / inclusion / exclusion section was identified"})
    unknown = sum(1 for sec in structure["sections"] if sec["category"] == "unknown")
    if structure["sections"] and unknown / len(structure["sections"]) > 0.5:
        warnings.append({"page": None, "severity": "warning", "code": "sections_mostly_unknown", "stage": "structure",
                         "message": f"{unknown} of {len(structure['sections'])} sections could not be classified"})
    if len(structure["sections"]) <= 2 and extraction["page_count"] > 10:
        warnings.append({"page": None, "severity": "warning", "code": "no_headings", "stage": "structure",
                         "message": "Very few headings detected; section boundaries may be unreliable"})
    if not meta.get("nct_id"):
        warnings.append({"page": None, "severity": "info", "code": "nct_not_found", "stage": "metadata",
                         "message": "No NCT registry identifier found in the document text"})
    for t in tables:
        for tw in t["warnings"]:
            warnings.append({"page": t["page"], "severity": "info", "code": "table_quality", "stage": "extraction", "message": tw})
    empty_secs = [sec for sec in structure["sections"] if sec["category"] in ("inclusion_criteria", "exclusion_criteria")
                  and not any(c["section_id"] == sec["id"] for c in chunks)]
    for sec in empty_secs:
        warnings.append({"page": sec["page_start"], "severity": "warning", "code": "empty_section", "stage": "structure",
                         "message": f"Section '{sec['title']}' has no extracted text"})

    analysis = {"sections": structure["sections"], "chunks": chunks, "tables": tables, "meta": meta, "ext": ext,
                "warnings": warnings, "abbreviations": abbrevs, "heading_source": structure["heading_source"],
                "toc_pages": structure["toc_pages"], "kind": extraction["kind"], "page_count": extraction["page_count"],
                "ocr_pages": sum(1 for p in extraction["pages"] if p["method"] == "ocr"),
                "mean_confidence": round(sum(p["confidence"] for p in extraction["pages"]) / max(1, len(extraction["pages"])), 3),
                "timing": {"extract_s": round(t_extract, 1), "analyze_s": round(time.time() - t0 - t_extract, 1)}}
    save_artifact(doc_id, "analysis", analysis)
    return {"doc_id": doc_id, "chunks": len(chunks), "claims": len(ext["claims"]), "timing": analysis["timing"]}


# ---------------------------------------------------------------------------
# Stage 6-7 (writer thread): metadata store + graph
# ---------------------------------------------------------------------------
def store_analysis(doc_id: str, a: dict) -> None:
    meta = a["meta"]
    with metadb.tx() as c:
        for t in ("warnings", "sections", "chunks", "doc_tables", "mentions"):
            c.execute(f"DELETE FROM {t} WHERE doc_id = ?", (doc_id,))
        c.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
        c.executemany("INSERT INTO sections(id, doc_id, parent_id, number, title, category, level, page_start, page_end, ord, detection) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      [(s["id"], doc_id, s["parent_id"], s["number"], s["title"], s["category"], s["level"], s["page_start"],
                        s["page_end"], s["ord"], s["detection"]) for s in a["sections"]])
        c.executemany("""INSERT INTO chunks(id, doc_id, section_id, parent_chunk_id, chunk_type, page_start, page_end, section_title,
                         section_category, text, bbox, extraction_method, extraction_confidence, table_id, document_version, ord)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      [(ch["id"], doc_id, ch["section_id"], ch["parent_chunk_id"], ch["chunk_type"], ch["page_start"], ch["page_end"],
                        ch["section_title"], ch["section_category"], ch["text"], json.dumps(ch["bbox"]), ch["extraction_method"],
                        ch["extraction_confidence"], ch["table_id"], ch["document_version"], ch["ord"]) for ch in a["chunks"]])
        c.executemany("INSERT INTO chunks_fts(text, chunk_id, doc_id) VALUES (?,?,?)",
                      [(ch["text"], ch["id"], doc_id) for ch in a["chunks"] if ch["chunk_type"] != "toc"])
        c.executemany("INSERT INTO doc_tables(id, doc_id, page, title, n_rows, n_cols, cells, bbox, warnings) VALUES (?,?,?,?,?,?,?,?,?)",
                      [(t["id"], doc_id, t["page"], t["title"], t["n_rows"], t["n_cols"], json.dumps(t["cells"]), json.dumps(t["bbox"]),
                        json.dumps(t["warnings"])) for t in a["tables"]])
        c.executemany("INSERT INTO warnings(doc_id, page, stage, severity, code, message) VALUES (?,?,?,?,?,?)",
                      [(doc_id, w.get("page"), w.get("stage"), w["severity"], w["code"], w["message"]) for w in a["warnings"]])
        c.executemany("INSERT INTO mentions(doc_id, entity_id, chunk_id, surface, page) VALUES (?,?,?,?,?)",
                      [(doc_id, m[0], m[1], m[2], m[3]) for m in a["ext"]["mentions"]])
        for abbr, cid in a.get("abbreviations", {}).items():
            cpt = L.BY_ID.get(cid)
            if cpt:
                c.execute("INSERT OR IGNORE INTO entity_aliases(entity_id, entity_type, name, alias, alias_norm, source) VALUES (?,?,?,?,?,?)",
                          (cid, cpt.type, cpt.name, abbr, norm(abbr), "document"))
        c.execute("""UPDATE documents SET title=?, doc_kind=?, page_count=?, nct_id=?, sponsor=?, sponsor_protocol_code=?, phase=?,
                     version_label=?, version_date=?, amendment=?, document_type=?, chunk_count=?, section_count=?, table_count=?,
                     extraction_confidence=? WHERE id=?""",
                  (meta.get("title"), a["kind"], a["page_count"], meta.get("nct_id"), meta.get("sponsor"), meta.get("sponsor_protocol_code"),
                   meta.get("phase"), meta.get("version_label"), meta.get("version_date"), meta.get("amendment"), meta.get("document_type"),
                   len(a["chunks"]), len(a["sections"]), len(a["tables"]), a["mean_confidence"], doc_id))


def apply_resolution(doc_id: str, a: dict) -> dict:
    """Resolve unknown drug-like candidates and add claims for confidently-used provisional drugs."""
    decisions = {(r["surface_norm"], r["entity_type"]): r for r in metadb.q("SELECT * FROM resolution_decisions")}
    res = resolve_candidates(doc_id, a["ext"]["candidates"], decisions)
    ext = a["ext"]
    known = {e["id"] for e in ext["entities"]}
    chunk_by_id = {c["id"]: c for c in a["chunks"]}
    for e in res["entities"]:
        if e["id"] not in known:
            ext["entities"].append(e)
    ext["mentions"] = ext["mentions"] + res["mentions"]
    # provisional drugs named in treatment sections of >= 2 passages get an INVESTIGATES claim (lower confidence)
    by_ent: dict[str, list] = {}
    for eid, chunk_id, surface, page in res["mentions"]:
        by_ent.setdefault(eid, []).append((chunk_id, surface))
    for eid, items in by_ent.items():
        chs = [chunk_by_id[c] for c, _ in items if c in chunk_by_id and chunk_by_id[c]["section_category"] in
               ("synopsis", "dosing", "treatment_arms", "study_design", "objectives", "title_page")]
        if len({c["id"] for c in chs}) < 2:
            continue
        evid = []
        for ch in chs[:4]:
            sf = next(s for c, s in items if c == ch["id"])
            pos = ch["text"].find(sf)
            q = ch["text"][max(0, pos - 160): pos + 200].strip() if pos >= 0 else ch["text"][:300]
            evid.append({"chunk_id": ch["id"], "page_start": ch["page_start"], "page_end": ch["page_end"], "quote": q,
                         "section": ch["section_title"], "section_category": ch["section_category"], "confidence": 0.55})
        cl_id = "clm_" + hashlib.sha1(f"{doc_id}|INVESTIGATES|protocol:{doc_id}|{eid}".encode()).hexdigest()[:16]
        if not any(c["id"] == cl_id for c in ext["claims"]):
            ext["claims"].append({"id": cl_id, "doc_id": doc_id, "predicate": "INVESTIGATES", "subject": f"protocol:{doc_id}",
                                  "object": eid, "method": "rule:unresolved-candidate", "assertion_type": "explicit",
                                  "confidence": 0.55, "evidence": evid, "evidence_count": len(chs),
                                  "qualifiers": {"role": "study treatment (unresolved term)"}})
    with metadb.tx() as c:
        c.execute("DELETE FROM resolution_review WHERE doc_id = ? AND status = 'pending'", (doc_id,))
        for r in res["review"]:
            dup = c.execute("SELECT 1 FROM resolution_review WHERE doc_id=? AND surface_norm=? AND status != 'pending'",
                            (doc_id, r["surface_norm"])).fetchone()
            if dup:
                continue
            c.execute("""INSERT INTO resolution_review(id, doc_id, surface, surface_norm, entity_type, provisional_entity_id,
                         candidate_entity_id, candidate_name, score, reason, status, context) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (metadb.new_id("rev"), doc_id, r["surface"], r["surface_norm"], r["entity_type"], r["provisional_entity_id"],
                       r["candidate_entity_id"], r["candidate_name"], r["score"], r["reason"], "pending", r["context"]))
    return res


def persist_document(doc_id: str) -> dict:
    from app.graph import writer  # local import keeps worker processes free of the Neo4j driver

    a = load_artifact(doc_id, "analysis")
    if a is None:
        raise RuntimeError("analysis artifact missing - re-run analysis")
    store_analysis(doc_id, a)
    metadb.execute("UPDATE documents SET stage='stored' WHERE id=?", (doc_id,))
    res = apply_resolution(doc_id, a)
    doc = metadb.q1("SELECT * FROM documents WHERE id = ?", (doc_id,))
    gres = writer.write_document(doc, a["sections"], a["chunks"], a["tables"], a["ext"])
    tk = writer.trial_key(doc)
    notes = writer.rebuild_versions(tk[0]) if tk else []
    with metadb.tx() as c:
        for rj in gres["rejected"][:200]:
            c.execute("INSERT INTO warnings(doc_id, page, stage, severity, code, message) VALUES (?,?,?,?,?,?)",
                      (doc_id, rj["evidence"][0]["page_start"] if rj.get("evidence") else None, "validation", "warning",
                       "relationship_rejected", f"{rj['predicate']} {rj['subject']} -> {rj['object']}: {rj['reason']}"))
        for n in notes:
            c.execute("INSERT INTO warnings(doc_id, page, stage, severity, code, message) VALUES (?,?,?,?,?,?)",
                      (doc_id, None, "versioning", "info", "version_order", n))
        if res["review"]:
            c.execute("INSERT INTO warnings(doc_id, page, stage, severity, code, message) VALUES (?,?,?,?,?,?)",
                      (doc_id, None, "resolution", "info", "ambiguous_entities",
                       f"{len(res['review'])} drug-like terms resemble known drugs and await review (not merged)"))
        c.execute("""UPDATE documents SET entity_count=?, relationship_count=?, stage='done', status='processed', processed_at=?, error=NULL
                     WHERE id=?""", (gres["entity_count"], gres["relationships"], time.time(), doc_id))
    try:  # a re-read document invalidates saved AI explanations
        metadb.execute("DELETE FROM ai_explanations WHERE doc_id=?", (doc_id,))
    except Exception:
        pass
    metadb.audit("document.processed", f"{doc['filename']}: {gres['relationships']} relationships, {gres['entity_count']} entities",
                 doc_id, {k: v for k, v in gres.items() if k != "rejected"} | {"rejected": len(gres["rejected"]), "timing": a["timing"]})
    return gres


def delete_document_everywhere(doc_id: str) -> None:
    from app.graph import writer

    doc = metadb.q1("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not doc:
        raise KeyError(doc_id)
    writer.delete_document(doc_id)
    tk = writer.trial_key(doc)
    if tk:
        writer.rebuild_versions(tk[0])
    s = get_settings()
    with metadb.tx() as c:
        c.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        try:
            c.execute("DELETE FROM ai_explanations WHERE doc_id = ?", (doc_id,))
        except Exception:
            pass
    (s.pdf_dir / doc["stored_name"]).unlink(missing_ok=True)
    shutil.rmtree(s.artifact_dir / doc_id, ignore_errors=True)
    metadb.audit("document.deleted", f"{doc['filename']} deleted (graph contributions removed, original file removed)", doc_id)
