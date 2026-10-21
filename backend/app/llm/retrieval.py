"""Retrieval for the AI assistant (the "R" in RAG), with an explanation of why each source was chosen.

Hybrid, fully local, no embedding model required:
1. keyword search (SQLite FTS5 / BM25) over every extracted passage, with question terms expanded by the curated
   terminology (brand names, codes, abbreviations of the drugs / biomarkers found in the question);
2. section-aware re-ranking: a question about eligibility prefers eligibility sections, a dosing question prefers dosing
   sections, and so on;
3. validated knowledge-graph facts (each with page + quote) when the question concerns the whole corpus.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.core import metadb
from app.extraction import lexicon as L

STOP = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is it its may me might
my no not of on or our should so than that the their them then there these they this those to was we were what when where which
who whom why will with would you your about across all any each other also please tell explain show give list describe study studies
protocol protocols trial trials document documents patient patients participant participants people person join need needs
compare comparison between versus given give receive received treatment treatments used use using much many often""".split())

# question cue -> section categories to prefer
INTENT_SECTIONS: list[tuple[str, list[str]]] = [
    (r"eligib|inclusion|include|qualif|who can|can i join|enrol|enroll|criteria|allowed", ["inclusion_criteria", "eligibility"]),
    (r"exclusion|exclude|cannot|can't|not allowed|prohibit|contraindicat", ["exclusion_criteria", "eligibility", "concomitant_medications"]),
    (r"dose|dosing|dosage|mg|schedule|administ|given|infusion|tablet|cycle|regimen|treatment|receiv|how often|how much",["dosing", "treatment_arms", "study_design"]),
    (r"arm|group|randomi|placebo|compar|versus|vs\b|design|blind|open-label|phase", ["study_design", "treatment_arms", "synopsis", "randomization"]),
    (r"endpoint|outcome|measure|primary|secondary|survival|response|pfs|\bos\b|orr|goal|objective|aim|purpose", ["primary_endpoints", "secondary_endpoints", "endpoints", "objectives", "synopsis"]),
    (r"side effect|adverse|toxicit|safety|risk|harm|neutropen|neuropath|pneumonitis", ["adverse_events", "safety_monitoring", "dosing"]),
    (r"statistic|sample size|power|hazard|analysis|analyse|analyze", ["statistics"]),
    (r"biomarker|her2|pd-?l1|brca|pik3ca|esr1|ki-?67|ctdna|receptor|test", ["biomarkers", "eligibility", "inclusion_criteria"]),
    (r"visit|assessment|scan|imaging|follow|blood test|schedule of", ["schedule_of_assessments", "study_procedures", "follow_up"]),
    (r"background|why|rationale|summary|overview|about|what is", ["synopsis", "background", "objectives"]),
]


def _terms(question: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/+.]*[A-Za-z0-9+]|[A-Za-z0-9]", question)
    out, seen = [], set()
    for t in toks:
        tl = t.lower()
        if tl in STOP or (len(t) < 2 and not t.isdigit()):
            continue
        if tl not in seen:
            seen.add(tl)
            out.append(t)
    return out


def _expansions(question: str) -> tuple[list[str], list[dict]]:
    """Synonyms (brand names, codes, abbreviations) for the concepts named in the question."""
    try:
        from app.extraction.entities import base_matcher
        mentions = base_matcher().find(question)
    except Exception:
        return [], []
    extra, concepts, seen = [], [], set()
    for m in mentions:
        if m.concept_id in seen:
            continue
        seen.add(m.concept_id)
        c = L.BY_ID.get(m.concept_id)
        if not c:
            continue
        names = [c.name, *c.aliases, *c.cs_aliases][:8]
        concepts.append({"id": c.id, "name": c.name, "type": c.type, "surface": m.surface,
                         "aliases": sorted({x.lower() for x in names + [m.surface] if 2 < len(x) < 40})})
        for a in names:
            if 2 < len(a) < 40 and a.lower() not in question.lower():
                extra.append(a)
    return extra[:16], concepts


def _fts_query(terms: list[str]) -> str:
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms if t.strip())


def retrieve(question: str, doc_id: str | None = None, k: int = 8, per_doc: int = 3) -> dict[str, Any]:
    terms = _terms(question)
    extra, concepts = _expansions(question)
    preferred: list[str] = []
    for rx, cats in INTENT_SECTIONS:
        if re.search(rx, question, re.I):
            preferred += [c for c in cats if c not in preferred]
    all_terms = terms + [e for e in extra if e not in terms]
    rows: list[dict] = []
    if all_terms:
        params: list[Any] = [_fts_query(all_terms)]
        where = "chunks_fts MATCH ?"
        if doc_id:
            where += " AND f.doc_id = ?"
            params.append(doc_id)
        try:
            rows = metadb.q(f"""SELECT c.id AS chunk_id, c.doc_id, c.page_start, c.page_end, c.section_title, c.section_category, c.chunk_type, c.text,
                                       d.filename, d.title, d.nct_id, bm25(chunks_fts) AS bm25
                                FROM chunks_fts f JOIN chunks c ON c.id = f.chunk_id JOIN documents d ON d.id = c.doc_id
                                WHERE {where} AND c.chunk_type != 'toc' ORDER BY bm25 LIMIT 120""", params)
        except Exception:
            rows = []
    if not rows and doc_id and preferred:  # nothing matched by keyword: fall back to the relevant sections of this protocol
        marks = ",".join("?" * len(preferred))
        rows = metadb.q(f"""SELECT c.id AS chunk_id, c.doc_id, c.page_start, c.page_end, c.section_title, c.section_category, c.chunk_type, c.text,
                                   d.filename, d.title, d.nct_id, 0.0 AS bm25
                            FROM chunks c JOIN documents d ON d.id = c.doc_id
                            WHERE c.doc_id = ? AND c.section_category IN ({marks}) AND c.chunk_type NOT IN ('toc','table_row') ORDER BY c.ord LIMIT 20""",
                        [doc_id, *preferred])
    scored = []
    lowered_terms = [t.lower() for t in all_terms]
    groups = [set(c["aliases"]) for c in concepts]
    in_concept = set().union(*groups) if groups else set()
    groups += [{t.lower()} for t in terms if t.lower() not in in_concept]
    for r in rows:
        text_l = (r["text"] or "").lower()
        hits = [t for t in lowered_terms if t in text_l]
        score = -float(r["bm25"] or 0.0)
        reasons = []
        if hits:
            reasons.append("matches: " + ", ".join(sorted(set(hits))[:6]))
        if r["section_category"] in preferred:
            boost = 1.0 + 0.6 * (len(preferred) - preferred.index(r["section_category"])) / len(preferred)
            score = score * boost + 2.0
            reasons.append(f"relevant section: {r['section_category']}")
        coverage = sum(1 for g in groups if any(a in text_l for a in g)) / max(1, len(groups))
        score += 20.0 * coverage
        if len(r["text"] or "") < 60:
            score -= 2.0
        scored.append((score, r, reasons))
    scored.sort(key=lambda x: -x[0])
    picked, per = [], defaultdict(int)
    for score, r, reasons in scored:
        if per[r["doc_id"]] >= (k if doc_id else per_doc):
            continue
        per[r["doc_id"]] += 1
        picked.append({"kind": "passage", "doc_id": r["doc_id"], "filename": r["filename"], "title": r["title"], "nct_id": r["nct_id"],
                       "page_start": r["page_start"], "page_end": r["page_end"], "section": r["section_title"], "section_category": r["section_category"],
                       "chunk_id": r["chunk_id"], "text": (r["text"] or "")[:1100], "score": round(score, 2), "why": "; ".join(reasons) or "keyword match"})
        if len(picked) >= k:
            break
    return {"sources": picked, "terms": terms, "expanded_terms": extra, "concepts": concepts, "preferred_sections": preferred}


def graph_facts(question: str, limit: int = 8) -> dict[str, Any]:
    """Validated knowledge-graph facts for a corpus-wide question (via the allow-listed graph query engine)."""
    from app.query.engine import run_query
    try:
        r = run_query(question, limit=25, record=False)
    except TypeError:
        r = run_query(question, limit=25)
    except Exception as e:  # graph offline or unsupported question
        return {"sources": [], "summary": "", "intent": None, "error": type(e).__name__}
    out, seen = [], set()
    for p in r.get("evidence_passages", []):
        key = (p["subject"], p["relationship"], p["object"], p["doc_id"])
        if key in seen:
            continue
        seen.add(key)
        rel = p["relationship"].lower().replace("_", " ")
        out.append({"kind": "fact", "doc_id": p["doc_id"], "filename": p.get("filename"), "title": p.get("document_title"), "nct_id": p.get("nct_id"),
                    "page_start": p["page_start"], "page_end": p["page_end"], "section": p.get("section"), "chunk_id": p["chunk_id"],
                    "text": f"Fact: {p['subject']} - {rel} - {p['object']}. Quote: \"{(p['quote'] or '')[:500]}\"",
                    "score": round(float(p.get("confidence") or 0), 2), "why": f"validated graph fact ({rel}), {p.get('support_level') or ''}".strip(", ")})
        if len(out) >= limit:
            break
    return {"sources": out, "summary": (r.get("answer_summary") or {}).get("text", ""), "intent": r.get("intent"),
            "matched": [m["name"] for m in r.get("matched_entities", [])], "validation": r.get("validation_status"), "query_id": r.get("query_id")}


def number_sources(groups: list[list[dict]], start: int = 1) -> list[dict]:
    """Merge source lists (dropping duplicate chunks) and number them S1, S2, ..."""
    out, seen = [], set()
    for g in groups:
        for s in g:
            key = (s.get("chunk_id"), s["kind"], s["text"][:80])
            if key in seen:
                continue
            seen.add(key)
            out.append({**s, "id": f"S{start + len(out)}"})
    return out


def render_sources(sources: list[dict], max_chars: int = 700) -> str:
    lines = []
    for s in sources:
        where = f"{s.get('filename') or s.get('doc_id')}, p.{s.get('page_start')}" + (f", section '{s['section']}'" if s.get("section") else "")
        lines.append(f"- ({where}) {' '.join(s['text'][:max_chars].split())} [{s['id']}]")
    return "\n".join(lines)
