"""Cross-protocol comparison engine.

For each comparison field every protocol gets its own values, each with the evidence that supports
it. Field status:
  same          - identical value sets in all protocols
  similar       - overlapping but not identical
  different     - all protocols have values, none shared
  conflicting   - same trial (shared ClinicalTrial) or same drug with incompatible stated values
  unavailable   - missing in one or more protocols (missing is NOT evidence of exclusion)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.core import metadb
from app.graph import neo4j_client as db

FIELDS = [
    ("phase", "Study phase", ["HAS_PHASE"]),
    ("design", "Study design", ["HAS_DESIGN"]),
    ("subtype", "Cancer subtype / disease", ["STUDIES"]),
    ("population", "Study population", ["HAS_POPULATION"]),
    ("setting", "Treatment setting / line", ["HAS_SETTING"]),
    ("drugs", "Investigational drugs & interventions", ["INVESTIGATES"]),
    ("arms", "Treatment arms", ["INCLUDES_ARM"]),
    ("dosing", "Dose & administration", ["HAS_DOSE_SPECIFICATION"]),
    ("cycle", "Treatment cycle", ["HAS_TREATMENT_CYCLE"]),
    ("inclusion", "Inclusion criteria", ["HAS_INCLUSION_CRITERION"]),
    ("exclusion", "Exclusion criteria", ["HAS_EXCLUSION_CRITERION"]),
    ("primary_endpoints", "Primary endpoints", ["HAS_PRIMARY_ENDPOINT"]),
    ("secondary_endpoints", "Secondary endpoints", ["HAS_SECONDARY_ENDPOINT"]),
    ("biomarkers", "Biomarkers", ["ASSOCIATED_WITH_BIOMARKER"]),
    ("safety", "Adverse events monitored", ["MONITORS_ADVERSE_EVENT"]),
    ("safety_rules", "Safety monitoring rules", ["HAS_SAFETY_RULE"]),
    ("follow_up", "Follow-up schedule", ["HAS_FOLLOW_UP"]),
    ("statistics", "Statistical methods", ["USES_STATISTICAL_METHOD"]),
]
TEXT_FIELDS = {"inclusion", "exclusion", "safety_rules", "follow_up", "arms"}


def _tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}


def compare_protocols(protocol_ids: list[str]) -> dict[str, Any]:
    protocol_ids = protocol_ids[:4]
    rows = db.read("""
        MATCH (p:Protocol) WHERE p.id IN $ids
        OPTIONAL MATCH (p)-[:VERSION_OF]->(t:ClinicalTrial)
        RETURN p.id AS id, p.name AS title, p.doc_id AS doc_id, p.nct_id AS nct, p.phase AS phase, p.version_label AS version,
               p.version_date AS version_date, p.amendment AS amendment, p.document_type AS document_type, t.id AS trial""",
                   {"ids": protocol_ids})
    prots = {r["id"]: r for r in rows}
    missing = [p for p in protocol_ids if p not in prots]
    rels = db.read("""
        MATCH (p:Protocol)-[r]->(x) WHERE p.id IN $ids AND r.claim_id IS NOT NULL
        OPTIONAL MATCH (x)-[d:DOSE_OF]->(drug)
        OPTIONAL MATCH (x)-[u:USES_INTERVENTION]->(armdrug)
        RETURN p.id AS pid, type(r) AS rel, x.id AS xid, x.name AS name, labels(x) AS labels, x.text AS text,
               x.dose_value AS dose_value, x.dose_unit AS dose_unit, x.frequency AS frequency, x.route AS route,
               drug.id AS drug_id, drug.name AS drug_name, collect(DISTINCT armdrug.name) AS arm_drugs,
               r.claim_id AS claim_id, r.supporting_quote AS quote, r.source_page_start AS page, r.source_document_id AS doc_id,
               r.extraction_confidence AS confidence, r.validation_status AS validation_status, r.assertion_type AS assertion_type,
               elementId(r) AS edge_id""", {"ids": protocol_ids})
    by_field: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    rel_to_field = {rt: f for f, _, rts in FIELDS for rt in rts}
    for r in rels:
        f = rel_to_field.get(r["rel"])
        if not f or r["validation_status"] not in ("validated", "low_confidence"):
            continue
        val = r["name"]
        key = r["xid"]
        if f == "dosing":
            val = f"{r['drug_name']}: {r['dose_value']} {r['dose_unit']}" + (f", {r['frequency']}" if r["frequency"] else "") + (f", {r['route']}" if r["route"] else "")
            key = f"{r['drug_id']}|{r['dose_value']}|{(r['dose_unit'] or '').lower()}|{(r['frequency'] or '').lower()}"
        elif f in ("inclusion", "exclusion", "safety_rules", "follow_up"):
            val = r["text"] or r["name"]
        elif f == "arms":
            val = f"{r['name']}: {', '.join(r['arm_drugs'])}" if r["arm_drugs"] else r["name"]
            key = "|".join(sorted(r["arm_drugs"])) or r["name"]
        by_field[f][r["pid"]].append({"key": key, "value": val, "evidence": {
            "claim_id": r["claim_id"], "quote": r["quote"], "page": r["page"], "doc_id": r["doc_id"], "edge_id": r["edge_id"],
            "confidence": r["confidence"], "validation_status": r["validation_status"]}, "drug_id": r["drug_id"]})

    same_trial = len({p["trial"] for p in prots.values() if p["trial"]}) == 1 and all(p["trial"] for p in prots.values()) and len(prots) > 1
    fields_out = []
    for f, label, _ in FIELDS:
        per = {pid: by_field[f].get(pid, []) for pid in prots}
        present = [pid for pid, v in per.items() if v]
        status, detail = _status(f, per, same_trial)
        fields_out.append({"field": f, "label": label, "status": status, "detail": detail,
                           "values": {pid: _dedupe(v)[:60] for pid, v in per.items()},
                           "available_in": present})
    shared = db.read("""
        MATCH (p:Protocol)-[r]->(x) WHERE p.id IN $ids AND r.claim_id IS NOT NULL
          AND NOT x:EligibilityCriterion AND NOT x:DoseSpecification AND NOT x:SafetyMonitoringRule AND NOT x:FollowUpProcedure
          AND NOT x:StudyArm AND NOT x:TreatmentCycle
        WITH x, collect(DISTINCT p.id) AS ps WHERE size(ps) = size($ids)
        RETURN x.id AS id, x.name AS name, labels(x) AS labels ORDER BY name LIMIT 60""", {"ids": list(prots)})
    docs = {d["id"]: d for d in metadb.q(
        f"SELECT id, filename, title, nct_id, version_label, version_date, amendment, document_type, page_count, sponsor FROM documents "
        f"WHERE id IN ({','.join('?' * len(prots))})", [p["doc_id"] for p in prots.values()])} if prots else {}
    return {"protocols": [{**p, "document": docs.get(p["doc_id"])} for p in prots.values()], "missing": missing,
            "same_trial": same_trial, "fields": fields_out, "shared_entities": shared,
            "note": "Information missing from a protocol is reported as unavailable - it is not evidence that the protocol excludes or prohibits it."}


def _dedupe(vals: list[dict]) -> list[dict]:
    seen, out = set(), []
    for v in vals:
        if v["key"] not in seen:
            seen.add(v["key"])
            out.append(v)
    return out


def _status(field: str, per: dict[str, list], same_trial: bool) -> tuple[str, str]:
    present = {pid: v for pid, v in per.items() if v}
    if len(per) < 2:
        return ("single", "")
    if len(present) < len(per):
        miss = len(per) - len(present)
        return ("unavailable", f"Not found in {miss} protocol(s); missing information is not evidence of absence.")
    if field in TEXT_FIELDS:
        sets = {pid: [_tokens(x["value"]) for x in v] for pid, v in present.items()}
        pids = list(sets)
        matched, total = 0, 0
        for a in pids[:1]:
            for ta in sets[a]:
                total += 1
                best = max((len(ta & tb) / max(1, len(ta | tb)) for b in pids[1:] for tb in sets[b]), default=0)
                if best >= 0.6:
                    matched += 1
        if total and matched == total and all(len(sets[p]) == len(sets[pids[0]]) for p in pids):
            return ("same" if not same_trial else "same", f"All {total} items have a close textual match.")
        if matched:
            st = "conflicting" if same_trial else "similar"
            return (st, f"{matched} of {total} items in the first protocol have a close match (token overlap >= 0.6)"
                        + ("; same registered trial - differences may reflect protocol amendments." if same_trial else "."))
        return ("conflicting" if same_trial else "different", "No closely matching items" + (" although the documents belong to the same trial." if same_trial else "."))
    keys = {pid: {x["key"] for x in v} for pid, v in present.items()}
    allk = list(keys.values())
    inter = set.intersection(*allk)
    union = set.union(*allk)
    if field == "dosing":
        # same drug, different stated dose in different protocols -> conflicting / different
        drugs = [{x["drug_id"] for x in v} for v in present.values()]
        common_drugs = set.intersection(*drugs)
        diff = [d for d in common_drugs if len({k for pid, v in present.items() for x in v if x["drug_id"] == d for k in [x["key"]]}) > len(present)]
        if inter == union:
            return ("same", "Identical dose statements.")
        if common_drugs and diff:
            return ("conflicting" if same_trial else "different",
                    f"{len(common_drugs)} shared drug(s) with differing dose/schedule statements" + (" in versions of the same trial." if same_trial else "."))
    if inter == union:
        return ("same", "Identical values.")
    if inter:
        return ("similar", f"{len(inter)} shared, {len(union) - len(inter)} protocol-specific.")
    return ("conflicting" if same_trial and field in ("phase",) else "different", "No shared values.")
