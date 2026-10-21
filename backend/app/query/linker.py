"""Query step 3 - resolve terms in the question to canonical graph entities.

Resolution order: NCT identifiers -> curated terminology matcher (synonyms, brands, codes,
abbreviations) -> graph full-text index over node names/aliases (provisional entities,
sponsors, protocol titles / trial acronyms). Every linked id is checked against the graph,
so a term only counts as resolved when the entity really exists in the indexed data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.extraction import lexicon as L
from app.extraction.entities import base_matcher, norm
from app.graph import neo4j_client as db
from app.graph.schema import primary_type

STOP = set("""a an the and or of in on with for to by from which what who whose where when how show find list give tell me all
any every each trials trial protocols protocol studies study investigate investigates investigating use uses using that
this these those are is do does did be been have has same different share shares across compare comparison between
breast cancer patients mention mentions mentioning context criteria inclusion exclusion eligibility drug drugs
intervention interventions dose doses dosing schedule schedules endpoint endpoints primary secondary biomarker
biomarkers adverse event events symptom symptoms source sources supporting contradicting claim about treatment path
paths trace relationship from its arm population similar like based other than more most common number count""".split())


@dataclass
class Linked:
    id: str
    name: str
    type: str
    surface: str
    method: str
    labels: list[str] = field(default_factory=list)


def _exists(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = db.read("MATCH (n:KG) WHERE n.id IN $ids RETURN n.id AS id, n.name AS name, labels(n) AS labels", {"ids": ids})
    return {r["id"]: r for r in rows}


def link_entities(question: str) -> tuple[list[Linked], list[str]]:
    linked: list[Linked] = []
    spans: list[tuple[int, int]] = []

    # NCT ids -> ClinicalTrial nodes
    for m in re.finditer(r"NCT\s?\d{8}", question, re.I):
        nid = "trial:" + re.sub(r"\s", "", m.group(0)).upper()
        linked.append(Linked(nid, nid.split(":")[1], "ClinicalTrial", m.group(0), "nct-id"))
        spans.append((m.start(), m.end()))
    # internal document ids (e.g. from "View protocol" links)
    for m in re.finditer(r"\b(protocol:)?(d[0-9a-f]{12})\b", question):
        linked.append(Linked(f"protocol:{m.group(2)}", m.group(2), "Protocol", m.group(0), "document-id"))
        spans.append((m.start(), m.end()))

    for m in base_matcher().find(question):
        if any(not (m.end <= a or m.start >= b) for a, b in spans):
            continue
        c = L.BY_ID[m.concept_id]
        linked.append(Linked(c.id, c.name, c.type, m.surface, m.method))
        spans.append((m.start, m.end))
    # class words ("chemotherapy", "CDK4/6 inhibitors", "PARP inhibitor") -> DrugClass
    for c in L.CONCEPTS:
        if c.type != "DrugClass":
            continue
        for form in {c.name.lower(), re.sub(r"\s*\(.*?\)", "", c.name.lower())}:
            for mm in re.finditer(r"(?<![a-z0-9])" + re.escape(form) + r"s?(?![a-z0-9])", question.lower()):
                if not any(not (mm.end() <= a or mm.start() >= b) for a, b in spans):
                    linked.append(Linked(c.id, c.name, "DrugClass", question[mm.start():mm.end()], "class-name"))
                    spans.append((mm.start(), mm.end()))

    # leftover candidate terms -> full-text search over graph names / aliases (acronyms, sponsors, provisional drugs)
    leftovers = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9\-+/']{2,}(?:\s+[A-Z0-9][A-Za-z0-9\-+/']*){0,3}", question):
        if any(not (m.end() <= a or m.start() >= b) for a, b in spans):
            continue
        term = m.group(0).strip()
        words = [w for w in re.split(r"\s+", term) if w.lower() not in STOP]
        if not words:
            continue
        term = " ".join(words)
        looks_named = bool(re.search(r"[A-Z].*\d|\d.*[A-Z]|[A-Z]{2,}|-", term)) or bool(L.DRUG_SUFFIX.search(term))
        if looks_named and len(term) >= 3:
            leftovers.append((term, m.start(), m.end()))
    unresolved: list[str] = []
    for term, s, e in leftovers:
        q = " AND ".join(f'"{w}"' for w in re.split(r"[\s/]+", re.sub(r'["\\]', "", term)) if w)
        rows = []
        try:
            rows = db.read("""CALL db.index.fulltext.queryNodes('kg_names', $q) YIELD node, score
                              WHERE NOT node:EvidenceChunk AND NOT node:ExtractedClaim AND NOT node:DocumentSection
                              RETURN node.id AS id, node.name AS name, labels(node) AS labels, score ORDER BY score DESC LIMIT 5""",
                           {"q": q})
        except Exception:
            rows = []
        best = None
        for r in rows:
            nm = norm(r["name"] or "")
            if norm(term) in nm or nm in norm(term):
                best = r
                break
        if best:
            linked.append(Linked(best["id"], best["name"], primary_type(best["labels"]), term, "graph-fulltext", best["labels"]))
        else:
            unresolved.append(term)

    exist = _exists([l.id for l in linked])
    final, seen = [], set()
    for l in linked:
        if l.id in exist and l.id not in seen:
            l.labels = exist[l.id]["labels"]
            l.type = primary_type(l.labels)
            final.append(l)
            seen.add(l.id)
        elif l.id not in exist:
            unresolved.append(f"{l.surface} (recognised as {l.type} '{l.name}' but not present in the indexed protocols)")
    return final, unresolved
