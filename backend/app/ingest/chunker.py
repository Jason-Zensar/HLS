"""Stage 4 - hierarchical, document-aware chunking.

Hierarchy: Document -> Section -> (Subsection) -> Paragraph / List item / Table -> Evidence chunk.

Rules
* Chunks never cross a section boundary.
* In eligibility, dosing, endpoint and arm sections every numbered/bulleted item stays one
  chunk (a criterion is never split, and its lettered sub-items stay attached).
* Tables become one `table` chunk (structure kept as rows) plus one `table_row` child per
  row, each row rendered with its column headers so it is searchable on its own.
* Long paragraphs are split only at sentence boundaries; short consecutive paragraphs in
  the same section are merged up to a soft size limit.
* Each chunk carries page_start/page_end and per-page bounding boxes for highlighting.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

ITEM_SECTIONS = {"inclusion_criteria", "exclusion_criteria", "eligibility", "dosing", "treatment_arms",
                 "primary_endpoints", "secondary_endpoints", "exploratory_endpoints", "endpoints", "objectives"}
SOFT_MAX = 1100      # merge target for short paragraphs (characters)
HARD_MAX = 2200      # split threshold for long paragraphs
ITEM_START = re.compile(r"^(\d{1,2}[.)]?|[•●▪–\-*·o]|\(?[ivx]{1,4}\)|[A-Z]\d{0,2}[.)])(\s+|$)")
SUBITEM = re.compile(r"^\(?[a-z]\)|^[a-z][.)]\s|^[•●▪–\-*·]\s?")
NUM_ALONE = re.compile(r"^\d{1,2}[.)]?$")
SENT_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")


def _cid(doc_id: str, *parts: Any) -> str:
    return "chk_" + hashlib.sha1("|".join([doc_id, *map(str, parts)]).encode()).hexdigest()[:16]


def _join_lines(lines: list[str]) -> str:
    out = ""
    for t in lines:
        if not out:
            out = t
        elif out.endswith("-") and len(out) > 1 and out[-2].islower() and t[:1].islower():
            out = out[:-1] + t
        else:
            out = out + " " + t
    return out.strip()


def _bbox_union(entries: list[tuple[int, list[float]]]) -> list[list[float]]:
    per: dict[int, list[float]] = {}
    for page, b in entries:
        if page in per:
            a = per[page]
            per[page] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        else:
            per[page] = list(b)
    return [[p, *map(lambda v: round(v, 1), bb)] for p, bb in sorted(per.items())]


def build_chunks(doc_id: str, extraction: dict[str, Any], structure: dict[str, Any],
                 document_version: str | None = None) -> dict[str, Any]:
    pages = extraction["pages"]
    sections = {s["id"]: s for s in structure["sections"]}
    line_section = structure["line_section"]
    heading_lines = structure["heading_lines"]
    chunks: list[dict] = []
    tables: list[dict] = []

    # ---- group lines into units (paragraphs / list items) per section ---------
    units: list[dict] = []
    cur: dict | None = None
    flat_idx = -1
    prev_line = None
    for pi, p in enumerate(pages):
        for li, l in enumerate(p["lines"]):
            flat_idx += 1
            if flat_idx in heading_lines or l.get("in_table"):
                if flat_idx in heading_lines:
                    cur = None
                continue
            sid = line_section.get((pi, li))
            sec = sections.get(sid, {})
            cat = sec.get("category", "unknown")
            t = l["text"]
            toc_page = l.get("toc_page", False)
            new_unit = cur is None or cur["section_id"] != sid or cur["toc"] != toc_page
            if not new_unit:
                gap = l["bbox"][1] - prev_line["bbox"][3] if prev_line and prev_line is not l else 0
                same_page = cur["entries"][-1][0] == p["page"]
                lh = max(l["bbox"][3] - l["bbox"][1], 6)
                if cat in ITEM_SECTIONS:
                    if NUM_ALONE.match(t) or (ITEM_START.match(t) and not SUBITEM.match(t)):
                        new_unit = True
                    elif same_page and gap > 1.6 * lh and not SUBITEM.match(t) and cur["text_lines"] \
                            and not cur["text_lines"][-1].endswith(":"):
                        new_unit = True
                else:
                    if same_page and (gap > 0.9 * lh or l["block"] != prev_line["block"] and gap > 0.4 * lh):
                        new_unit = True
                    elif ITEM_START.match(t) and cur["text_lines"] and cur["text_lines"][-1].endswith((".", ":")):
                        new_unit = True
            if new_unit:
                cur = {"section_id": sid, "category": cat, "text_lines": [], "entries": [], "toc": toc_page,
                       "is_item": cat in ITEM_SECTIONS and bool(NUM_ALONE.match(t) or ITEM_START.match(t)),
                       "methods": set(), "conf": []}
                units.append(cur)
            if NUM_ALONE.match(t) and not cur["text_lines"]:
                cur["item_number"] = t.rstrip(".)")
            else:
                cur["text_lines"].append(t)
            cur["entries"].append((p["page"], l["bbox"]))
            cur["methods"].add(p["method"])
            cur["conf"].append(l.get("ocr_conf", p.get("confidence", 1.0)))
            prev_line = l

    # ---- turn units into chunks (merge short / split long) ----------------------
    ord_ = 0
    pending: list[dict] = []

    def emit(group: list[dict], chunk_type: str):
        nonlocal ord_
        text = "\n".join(_join_lines(u["text_lines"]) for u in group).strip()
        if not text:
            return
        if group[0].get("item_number"):
            text = f"{group[0]['item_number']}. {text}"
        entries = [e for u in group for e in u["entries"]]
        sec = sections.get(group[0]["section_id"], {})
        confs = [c for u in group for c in u["conf"]]
        methods = sorted({m for u in group for m in u["methods"]})
        for part_i, part in enumerate(_split_long(text)):
            chunks.append({
                "id": _cid(doc_id, "p", ord_, part_i, part[:40]), "doc_id": doc_id,
                "section_id": group[0]["section_id"], "parent_chunk_id": None,
                "chunk_type": "toc" if group[0]["toc"] else chunk_type,
                "page_start": min(e[0] for e in entries), "page_end": max(e[0] for e in entries),
                "section_title": sec.get("title", ""), "section_category": sec.get("category", "unknown"),
                "text": part, "bbox": _bbox_union(entries), "extraction_method": "+".join(methods),
                "extraction_confidence": round(min(confs) if confs else 1.0, 3), "table_id": None,
                "document_version": document_version, "ord": ord_,
            })
            ord_ += 1

    def flush():
        if pending:
            emit(list(pending), "paragraph")
            pending.clear()

    for u in units:
        text = _join_lines(u["text_lines"])
        if not text and not u.get("item_number"):
            continue
        if u["is_item"] or u["category"] in ITEM_SECTIONS:
            flush()
            emit([u], "list_item" if u["is_item"] else "paragraph")
            continue
        if pending and (pending[0]["section_id"] != u["section_id"] or
                        sum(len(_join_lines(x["text_lines"])) for x in pending) + len(text) > SOFT_MAX):
            flush()
        pending.append(u)
    flush()

    # ---- tables ------------------------------------------------------------------
    for pi, p in enumerate(pages):
        for ti, t in enumerate(p["tables"]):
            tid = "tbl_" + hashlib.sha1(f"{doc_id}|{p['page']}|{ti}".encode()).hexdigest()[:14]
            # section = section of nearest preceding line on the page
            sid = None
            for li, l in enumerate(p["lines"]):
                if l["bbox"][1] <= t["bbox"][1] + 2:
                    sid = line_section.get((pi, li), sid)
            if sid is None:
                sid = next((line_section[(pi, li)] for li in range(len(p["lines"])) if (pi, li) in line_section),
                           structure["sections"][0]["id"])
            sec = sections.get(sid, {})
            rows = t["rows"]
            tables.append({"id": tid, "doc_id": doc_id, "page": p["page"], "title": t["title"],
                           "n_rows": t["n_rows"], "n_cols": t["n_cols"], "cells": rows, "bbox": t["bbox"],
                           "warnings": t["warnings"], "section_id": sid})
            header = rows[0]
            preview = "\n".join(" | ".join(c for c in r) for r in rows[:60])
            tchunk = {
                "id": _cid(doc_id, "t", tid), "doc_id": doc_id, "section_id": sid, "parent_chunk_id": None,
                "chunk_type": "table", "page_start": p["page"], "page_end": p["page"],
                "section_title": sec.get("title", ""), "section_category": sec.get("category", "unknown"),
                "text": ((t["title"] + "\n") if t["title"] else "") + preview,
                "bbox": [[p["page"], *t["bbox"]]], "extraction_method": "pymupdf-table",
                "extraction_confidence": 0.7 if t["warnings"] else 0.9, "table_id": tid,
                "document_version": document_version, "ord": ord_,
            }
            ord_ += 1
            chunks.append(tchunk)
            for ri, r in enumerate(rows[1:], start=1):
                cells = []
                for ci, c in enumerate(r):
                    if not c:
                        continue
                    h = header[ci] if ci < len(header) and header[ci] and header[ci] != c else ""
                    cells.append(f"{h}: {c}" if h else c)
                rt = "; ".join(cells)
                if len(rt) < 8:
                    continue
                chunks.append({
                    "id": _cid(doc_id, "r", tid, ri), "doc_id": doc_id, "section_id": sid,
                    "parent_chunk_id": tchunk["id"], "chunk_type": "table_row", "page_start": p["page"],
                    "page_end": p["page"], "section_title": sec.get("title", ""),
                    "section_category": sec.get("category", "unknown"),
                    "text": (f"[{t['title']}] " if t["title"] else "") + rt,
                    "bbox": [[p["page"], *t["bbox"]]], "extraction_method": "pymupdf-table",
                    "extraction_confidence": 0.7 if t["warnings"] else 0.85, "table_id": tid,
                    "document_version": document_version, "ord": ord_,
                })
                ord_ += 1
    return {"chunks": chunks, "tables": tables}


def _split_long(text: str) -> list[str]:
    if len(text) <= HARD_MAX:
        return [text]
    sents = SENT_SPLIT.split(text)
    parts, cur = [], ""
    for s in sents:
        if cur and len(cur) + len(s) > SOFT_MAX:
            parts.append(cur.strip())
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur.strip():
        parts.append(cur.strip())
    # a single sentence longer than HARD_MAX is kept whole (never cut mid-sentence)
    return parts
