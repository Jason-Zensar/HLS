"""Deterministic, plain-language structure of one protocol ("protocol at a glance").

Built only from validated graph facts (each with page + quote) and the protocol's own key sections, so it works without
any AI model. It is shown on the protocol page and is also the grounding material for the AI explanation.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.core import metadb
from app.graph import neo4j_client as db
from app.llm.glossary import drug_reference, explain_terms

PHASE_EXPLAIN = {
    "1": "Early study in a small group to find a safe dose and learn about side effects.",
    "2": "Checks whether the treatment shows signs of working, while continuing to watch safety.",
    "3": "Large study comparing the new treatment with the current standard treatment.",
    "4": "Study of a treatment that is already approved, to learn more about long-term use.",
}

GROUPS = [
    ("treatments", "What participants receive", ["INVESTIGATES", "INCLUDES_ARM", "HAS_DOSE_SPECIFICATION", "HAS_TREATMENT_CYCLE"]),
    ("who_can_join", "Who can take part (inclusion criteria)", ["HAS_INCLUSION_CRITERION"]),
    ("who_cannot", "Who cannot take part (exclusion criteria)", ["HAS_EXCLUSION_CRITERION"]),
    ("measures", "What the study measures (endpoints)", ["HAS_PRIMARY_ENDPOINT", "HAS_SECONDARY_ENDPOINT", "HAS_EXPLORATORY_ENDPOINT", "MEASURES_ENDPOINT"]),
    ("safety", "Safety: side effects watched and safety rules", ["MONITORS_ADVERSE_EVENT", "HAS_SAFETY_RULE"]),
    ("biomarkers", "Tests and biomarkers", ["ASSOCIATED_WITH_BIOMARKER", "REQUIRES_ASSESSMENT"]),
    ("follow_up", "Follow-up and analysis", ["HAS_FOLLOW_UP", "USES_STATISTICAL_METHOD"]),
]
SUBLABEL = {"HAS_INCLUSION_CRITERION": "Must have / must be", "HAS_EXCLUSION_CRITERION": "Must not have / must not be",
            "INVESTIGATES": "Study treatment", "INCLUDES_ARM": "Treatment group", "HAS_DOSE_SPECIFICATION": "Dose", "HAS_TREATMENT_CYCLE": "Cycle",
            "HAS_PRIMARY_ENDPOINT": "Main goal (primary)", "HAS_SECONDARY_ENDPOINT": "Other goals (secondary)",
            "HAS_EXPLORATORY_ENDPOINT": "Exploratory", "MEASURES_ENDPOINT": "Measured", "MONITORS_ADVERSE_EVENT": "Side effects watched",
            "HAS_SAFETY_RULE": "Safety rule", "ASSOCIATED_WITH_BIOMARKER": "Biomarker", "REQUIRES_ASSESSMENT": "Test / assessment",
            "HAS_FOLLOW_UP": "Follow-up", "USES_STATISTICAL_METHOD": "Statistical method"}
KEY_CATEGORIES = ["synopsis", "objectives", "study_design", "treatment_arms", "dosing", "primary_endpoints"]


def _facts(doc_id: str) -> list[dict]:
    return db.read("""
        MATCH (p:Protocol {id: $pid})-[r]->(x) WHERE r.claim_id IS NOT NULL AND r.validation_status IN ['validated', 'low_confidence']
        OPTIONAL MATCH (x)-[:DOSE_OF]->(drug)
        OPTIONAL MATCH (x)-[:USES_INTERVENTION]->(armdrug)
        RETURN type(r) AS rel, x.id AS xid, x.name AS name, x.text AS text, labels(x) AS labels,
               x.dose_value AS dose_value, x.dose_unit AS dose_unit, x.frequency AS frequency, x.route AS route,
               drug.name AS drug_name, collect(DISTINCT armdrug.name) AS arm_drugs,
               r.supporting_quote AS quote, r.source_page_start AS page, r.source_chunk_id AS chunk_id, r.extraction_confidence AS confidence""",
                   {"pid": f"protocol:{doc_id}"})


def _value(f: dict) -> str:
    if f["rel"] == "HAS_DOSE_SPECIFICATION":
        v = f"{f['drug_name'] or ''} {f['dose_value'] or ''} {f['dose_unit'] or ''}".strip()
        return v + (f", {f['frequency']}" if f["frequency"] else "") + (f", {f['route']}" if f["route"] else "")
    if f["rel"] == "INCLUDES_ARM":
        return f"{f['name']}: {', '.join(f['arm_drugs'])}" if f["arm_drugs"] else f["name"]
    if f["rel"] in ("HAS_INCLUSION_CRITERION", "HAS_EXCLUSION_CRITERION", "HAS_SAFETY_RULE", "HAS_FOLLOW_UP"):
        t = (f["text"] or f["name"] or "").strip()
        return t[3:].strip() if t[:3].rstrip(".) ").isdigit() else t
    return f["name"] or ""


def build_brief(doc_id: str) -> dict[str, Any]:
    d = metadb.q1("""SELECT id, filename, title, nct_id, sponsor, sponsor_protocol_code, phase, version_label, version_date, amendment,
                            document_type, page_count, status FROM documents WHERE id=?""", (doc_id,))
    if not d:
        raise KeyError(doc_id)
    try:
        facts = _facts(doc_id)
        graph_ok = True
    except Exception:  # graph offline: the brief still shows document data and key sections
        facts, graph_ok = [], False
    by_rel: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for f in sorted(facts, key=lambda x: -(x["confidence"] or 0)):
        val = _value(f)
        k = (f["rel"], val.lower())
        if not val or k in seen:
            continue
        seen.add(k)
        by_rel[f["rel"]].append({"text": val, "xid": f["xid"], "evidence": {"doc_id": doc_id, "page": f["page"], "chunk_id": f["chunk_id"], "quote": f["quote"]}})

    def names(rel: str) -> list[str]:
        return [x["text"] for x in by_rel.get(rel, [])]

    phase = (d["phase"] or (names("HAS_PHASE") or [""])[0] or "").strip()
    phase_digit = next((ch for ch in phase if ch.isdigit()), "")
    facts_out = [
        {"label": "Study title", "value": _clean_title(d["title"]) or d["filename"]},
        {"label": "Study phase", "value": phase or "not stated", "explain": PHASE_EXPLAIN.get(phase_digit)},
        {"label": "Study design", "value": ", ".join(names("HAS_DESIGN")) or "not stated",
         "explain": " ".join(e["explanation"] for e in explain_terms(" ".join(names("HAS_DESIGN")), 3)) or None},
        {"label": "Disease studied", "value": ", ".join(names("STUDIES")) or "not stated"},
        {"label": "Treatment setting", "value": ", ".join(names("HAS_SETTING")) or "not stated",
         "explain": " ".join(e["explanation"] for e in explain_terms(" ".join(names("HAS_SETTING")), 2)) or None},
        {"label": "Population", "value": ", ".join(names("HAS_POPULATION")) or "not stated"},
        {"label": "Sponsor", "value": d["sponsor"] or "not stated"},
        {"label": "Trial ID", "value": " / ".join(x for x in (d["nct_id"], d["sponsor_protocol_code"]) if x) or "not stated",
         "explain": "NCT numbers can be looked up on ClinicalTrials.gov." if d["nct_id"] else None},
        {"label": "Document", "value": f"{d['document_type'] or 'protocol'}, {d['page_count']} pages"
                                       + (f", version {d['version_label']}" if d["version_label"] else "") + (f", dated {d['version_date']}" if d["version_date"] else "")
                                       + (f", amendment {d['amendment']}" if d["amendment"] else "")},
    ]

    sections = []
    for key, title, rels in GROUPS:
        groups = []
        for rel in rels:
            items = by_rel.get(rel, [])
            if items:
                limit = 30 if rel in ("HAS_INCLUSION_CRITERION", "HAS_EXCLUSION_CRITERION") else 15
                groups.append({"label": SUBLABEL.get(rel, rel), "items": items[:limit], "total": len(items)})
        sections.append({"key": key, "title": title, "groups": groups})

    drugs = names("INVESTIGATES")
    one_line = _one_liner(phase, names("HAS_DESIGN"), drugs, names("STUDIES"), names("HAS_SETTING"))

    key_passages = []
    for cat in KEY_CATEGORIES:
        rows = metadb.q("""SELECT id, section_title, page_start, text FROM chunks WHERE doc_id=? AND section_category=? AND chunk_type NOT IN ('toc','table_row')
                           ORDER BY ord LIMIT 3""", (doc_id, cat))
        for r in rows:
            key_passages.append({"category": cat, "section": r["section_title"], "page": r["page_start"], "chunk_id": r["id"], "text": r["text"][:1500]})

    blob = " ".join([one_line, d["title"] or ""] + [x["text"] for v in by_rel.values() for x in v] + [k["text"][:600] for k in key_passages])
    return {"doc": d, "graph_available": graph_ok, "one_liner": one_line, "facts": facts_out, "sections": sections,
            "key_passages": key_passages, "glossary": explain_terms(blob, 40),
            "drug_reference": drug_reference([x["xid"] for x in by_rel.get("INVESTIGATES", [])]),
            "counts": {k: len(v) for k, v in by_rel.items()}}


def _clean_title(t: str | None) -> str:
    import re
    t = re.sub(r"(?i)\b(official protocol title|protocol title|nct number|document date|study title)\s*:\s*", "", t or "")
    return re.sub(r"\s{2,}", " ", t).strip(" :-")


def _one_liner(phase: str, design: list[str], drugs: list[str], disease: list[str], setting: list[str]) -> str:
    parts = ["A"]
    if phase:
        parts.append(phase)
    if design:
        parts.append(", ".join(x.lower() for x in design[:3]))
    parts.append("study")
    s = " ".join(parts)
    if drugs:
        s += " of " + (", ".join(drugs[:4]) if len(drugs) <= 4 else ", ".join(drugs[:4]) + f" and {len(drugs) - 4} more")
    if disease:
        s += " in " + ", ".join(x.lower() for x in disease[:2])
    if setting:
        s += f" ({', '.join(x.lower() for x in setting[:2])} setting)"
    return s + "."


def brief_as_context(b: dict) -> tuple[str, list[dict]]:
    """Render the brief + key passages as numbered sources for the model."""
    sources: list[dict] = []
    d = b["doc"]

    def add(kind: str, text: str, page: int | None, chunk_id: str | None, section: str | None) -> str:
        sid = f"S{len(sources) + 1}"
        why = {"fact": "structured protocol fact", "reference": "reference terminology (general drug knowledge, not from this protocol)"}.get(kind, f"key section: {section}")
        sources.append({"id": sid, "kind": kind, "doc_id": d["id"], "filename": d["filename"], "title": d["title"], "nct_id": d["nct_id"],
                        "page_start": page, "section": section, "chunk_id": chunk_id, "text": text, "why": why})
        return sid

    lines = [f"PROTOCOL: {d['title'] or d['filename']} (file {d['filename']}; trial id {d['nct_id'] or 'n/a'}; phase {d['phase'] or 'n/a'}; sponsor {d['sponsor'] or 'n/a'})",
             f"SUMMARY (generated from facts): {b['one_liner']}"]
    budget = 36
    for sec in b["sections"]:
        for g in sec["groups"]:
            for it in g["items"][:8 if sec["key"] in ("who_can_join", "who_cannot") else 4]:
                if budget <= 0:
                    break
                budget -= 1
                ev = it["evidence"]
                sid = add("fact", f"{sec['title']} - {g['label']}: {it['text']}" + (f" | quote: \"{(ev['quote'] or '')[:220]}\"" if ev.get("quote") else ""),
                          ev.get("page"), ev.get("chunk_id"), sec["title"])
                lines.append(f"- {sec['title']} / {g['label']}: {it['text'][:240]} (page {ev.get('page')}) [{sid}]")
    for kp in b["key_passages"][:5]:
        sid = add("passage", kp["text"][:600], kp["page"], kp["chunk_id"], kp["section"])
        lines.append(f"- Passage from section '{kp['section']}' (page {kp['page']}): {kp['text'][:600]} [{sid}]")
    for r in b.get("drug_reference", [])[:8]:
        if r["explanation"]:
            sid = add("reference", f"{r['drug']} - {r['explanation']}", None, None, "Drug reference")
            lines.append(f"- Drug reference (general knowledge, not from the protocol): {r['drug']} - {r['explanation']} [{sid}]")
    return "\n".join(lines), sources
