"""Entity resolution and canonicalisation.

Order of evidence (most to least reliable):
1. Exact / normalised match against the curated terminology resource (lexicon) - resolved.
2. Document-local abbreviation definitions ("Trastuzumab deruxtecan (T-DXd; AZD4552)") - resolved,
   recorded as a document-sourced alias.
3. Stored human decisions (merge / keep separate) for a surface form - applied as decided.
4. Drug-like terms not in the dictionary:
   * string similarity to a known concept >= REVIEW_THRESHOLD -> provisional entity + review item
     (NOT merged: similar names are often different molecules, e.g. trastuzumab vs trastuzumab
     emtansine, or biosimilar codes);
   * otherwise -> provisional "unresolved" entity, kept separate.
Embedding similarity is deliberately not used to merge anything.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache

from app.extraction import lexicon as L
from app.extraction.entities import norm

REVIEW_THRESHOLD = 0.84
MIN_CANDIDATE_CHUNKS = 2


@lru_cache(maxsize=1)
def _drug_alias_index() -> list[tuple[str, str]]:
    out = []
    for c in L.CONCEPTS:
        if c.type == "Drug":
            for a in [c.name, *c.aliases, *c.cs_aliases]:
                out.append((norm(a), c.id))
    return out


def best_known_match(surface: str) -> tuple[str | None, float]:
    s = norm(surface)
    best, score = None, 0.0
    for a, cid in _drug_alias_index():
        if abs(len(a) - len(s)) > max(4, len(s) // 2):
            continue
        r = SequenceMatcher(None, s, a).ratio()
        if r > score:
            best, score = cid, r
    return best, score


def resolve_candidates(doc_id: str, candidates: list[dict], decisions: dict[tuple[str, str], dict]) -> dict:
    """Group unknown drug-like surfaces and decide what to do with each.

    Returns {"entities": [...], "mentions": [...], "review": [...], "remap": {surface_norm: entity_id}}
    """
    by_surface: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_surface[norm(c["surface"])].append(c)
    entities, mentions, review, remap = [], [], [], {}
    for s_norm, items in by_surface.items():
        chunks = {i["chunk_id"] for i in items}
        if len(chunks) < MIN_CANDIDATE_CHUNKS and not any(i["section_category"] == "title_page" for i in items):
            continue
        if re.fullmatch(r"[a-z]{2,5}-?\d{3,7}", s_norm) and len(chunks) < 3:
            continue  # bare development codes need more support
        surface = Counter(i["surface"] for i in items).most_common(1)[0][0]
        dec = decisions.get((s_norm, "Drug"))
        if dec and dec["decision"] == "merge" and dec.get("target_entity_id"):
            eid = dec["target_entity_id"]
            remap[s_norm] = eid
            for i in items:
                mentions.append((eid, i["chunk_id"], i["surface"], i["page"]))
            continue
        eid = f"drug:x-{L.slug(s_norm)}"
        cand, score = best_known_match(surface)
        status = "unresolved"
        if dec and dec["decision"] == "separate":
            status = "reviewed-separate"
        elif cand and score >= REVIEW_THRESHOLD:
            status = "ambiguous"
            review.append({"doc_id": doc_id, "surface": surface, "surface_norm": s_norm, "entity_type": "Drug",
                           "provisional_entity_id": eid, "candidate_entity_id": cand,
                           "candidate_name": L.BY_ID[cand].name, "score": round(score, 3),
                           "reason": f"string similarity {score:.2f} to '{L.BY_ID[cand].name}' - not merged automatically",
                           "context": items[0]["context"]})
        entities.append({"id": eid, "type": "Drug", "name": surface, "labels": [], "scope": "canonical",
                         "resolution_status": status,
                         "props": {"method": items[0]["method"], "candidate_match": L.BY_ID[cand].name if cand and score >= REVIEW_THRESHOLD else None,
                                   "candidate_score": round(score, 3) if cand else None}})
        for i in items:
            mentions.append((eid, i["chunk_id"], i["surface"], i["page"]))
        remap[s_norm] = eid
    return {"entities": entities, "mentions": mentions, "review": review, "remap": remap}


def lexicon_alias_rows() -> list[tuple]:
    rows = []
    for c in L.CONCEPTS:
        for a in {c.name, *c.aliases, *c.cs_aliases}:
            rows.append((c.id, c.type, c.name, a, norm(a), "lexicon"))
    return rows
