"""Query steps 1-4 - parse the question, detect intent, choose graph patterns.

The planner is deterministic: regex cues + the types of the linked entities select one or more
allowlisted templates. If a question cannot be mapped safely it returns intent "unsupported" with
an explanation instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.graph.schema import CLINICAL, EXPLORABLE
from app.query.linker import Linked

INTERVENTION = {"Drug", "Intervention", "CombinationTherapy"}
CONDITION = {"CancerSubtype", "Disease", "TreatmentSetting", "StudyPopulation"}
SIMILAR_RELS = ["INVESTIGATES", "STUDIES", "ASSOCIATED_WITH_BIOMARKER", "HAS_PRIMARY_ENDPOINT", "HAS_SETTING", "HAS_DESIGN"]
SHARED_RELS = ["INVESTIGATES", "ASSOCIATED_WITH_BIOMARKER", "HAS_PRIMARY_ENDPOINT", "STUDIES"]
OVERVIEW_RELS = sorted(CLINICAL - {"HAS_INCLUSION_CRITERION", "HAS_EXCLUSION_CRITERION", "HAS_SAFETY_RULE", "HAS_FOLLOW_UP"})
PATH_RELS = sorted(EXPLORABLE - {"MENTIONS", "BELONGS_TO_CLASS", "SUBCLASS_OF"}) + ["BELONGS_TO_CLASS"]


@dataclass
class Step:
    template: str
    params: dict
    purpose: str


@dataclass
class Plan:
    intent: str
    interpreted: str
    anchors: list[Linked]
    steps: list[Step] = field(default_factory=list)
    traversal: dict = field(default_factory=lambda: {"strategy": "bfs", "max_depth": 3})
    answer_types: list[str] = field(default_factory=list)   # node types that constitute "answers"
    notes: list[str] = field(default_factory=list)


def _first(anchors: list[Linked], types: set[str]) -> Linked | None:
    return next((a for a in anchors if a.type in types), None)


def _all(anchors: list[Linked], types: set[str]) -> list[Linked]:
    return [a for a in anchors if a.type in types]


def plan_query(question: str, anchors: list[Linked], limit: int = 25, strategy: str = "bfs") -> Plan:
    q = question.lower()
    iv = _all(anchors, INTERVENTION)
    cls = _all(anchors, {"DrugClass"})
    cond = _all(anchors, CONDITION)
    bm = _all(anchors, {"Biomarker"})
    ae = _all(anchors, {"AdverseEvent"})
    ep = _all(anchors, {"Endpoint"})
    prot = _all(anchors, {"Protocol"})
    trials = _all(anchors, {"ClinicalTrial"})
    base = {"limit": limit, "per": 30}
    P = lambda intent, txt, **kw: Plan(intent, txt, anchors, traversal={"strategy": strategy, "max_depth": 4}, **kw)

    # protocol references through NCT ids -> use their protocols
    if trials and not prot:
        prot = trials  # templates accept ClinicalTrial ids through overview fallback below

    # ---- comparison ------------------------------------------------------------
    if re.search(r"\bcompar", q) and len(prot) >= 2:
        pl = P("compare_protocols", f"Compare {', '.join(p.name[:40] for p in prot)}", answer_types=["Protocol"])
        for p in prot[:4]:
            pl.steps.append(Step("protocol_overview", {**base, "id": p.id, "rels": OVERVIEW_RELS}, f"structure of {p.name[:40]}"))
            if re.search(r"eligib|inclusion|exclusion|criteria", q):
                pl.steps.append(Step("eligibility_of_protocol", {**base, "id": p.id}, f"criteria of {p.name[:40]}"))
        pl.notes.append("Detailed field-by-field comparison is available in the Protocol Comparison view.")
        return pl
    # ---- similarity / shared -------------------------------------------------------
    if re.search(r"similar|alike|resembl", q) and prot:
        return P("similar_protocols", f"Protocols similar to {prot[0].name[:60]}", answer_types=["Protocol"],
                 steps=[Step("similar_protocols", {**base, "limit": min(limit, 10), "id": prot[0].id, "rels": SIMILAR_RELS},
                             "Jaccard similarity over treatments, subtypes, biomarkers, primary endpoints, settings, design")])
    if re.search(r"\bshar(e|es|ing|ed)\b|in common|same (drug|biomarker|primary endpoint|endpoint|intervention|subtype)", q):
        if prot:
            return P("shared_with_protocol", f"Protocols sharing entities with {prot[0].name[:60]}", answer_types=["Protocol"],
                     steps=[Step("shared_with_protocol", {**base, "limit": min(limit, 12), "id": prot[0].id, "rels": SHARED_RELS}, "shared entities")])
        rel = ("HAS_PRIMARY_ENDPOINT" if "endpoint" in q else "ASSOCIATED_WITH_BIOMARKER" if "biomarker" in q
               else "STUDIES" if "subtype" in q else "INVESTIGATES")
        if iv and rel == "INVESTIGATES" and "different" in q and "endpoint" in q:
            pass
        else:
            return P("shared_entities", f"Entities shared by multiple protocols via {rel}", answer_types=["Protocol"],
                     steps=[Step("shared_entities_global", {**base, "per": 8, "rel": rel}, f"top shared targets of {rel}")])
    # ---- same intervention, different primary endpoints ------------------------------
    if re.search(r"different (primary )?endpoints?", q) or ("same" in q and "endpoint" in q and "different" in q):
        return P("same_intervention_diff_endpoints",
                 "Protocols sharing an intervention but with different primary endpoints" + (f" ({iv[0].name})" if iv else ""),
                 answer_types=["Protocol", "Endpoint"],
                 steps=[Step("same_intervention_diff_primary_endpoints", {**base, "limit": min(limit, 20), "id": iv[0].id if iv else None},
                             "shared INVESTIGATES + non-overlapping HAS_PRIMARY_ENDPOINT")])
    # ---- dosing schedules / claims about schedules --------------------------------------
    if iv and re.search(r"\bdos(e|es|ing|age)\b|schedule|regimen|mg\b|cycle", q):
        intent = "schedule_claims" if re.search(r"support|contradict|conflict|claim|evidence", q) else "dosing_variation"
        return P(intent, f"Dose / schedule specifications of {iv[0].name} across protocols", answer_types=["DoseSpecification"],
                 steps=[Step("dosing_for_drug", {**base, "id": iv[0].id}, "protocol-specific DoseSpecification nodes")])
    # ---- adverse events with an intervention ---------------------------------------------
    if iv and (ae or re.search(r"adverse|toxicit|side effect|safety", q)):
        pl = P("adverse_events_for_intervention", f"Adverse events described with {iv[0].name}" + (f" - {ae[0].name}" if ae else ""),
               answer_types=["AdverseEvent", "Protocol"])
        pl.steps.append(Step("drug_adverse_events", {**base, "id": iv[0].id, "ae": ae[0].id if ae else None},
                             "drug-level AE statements in protocols (not causal)"))
        if ae:
            pl.steps.append(Step("drug_ae_monitoring", {**base, "id": iv[0].id, "ae": ae[0].id}, "protocols monitoring the AE"))
        return pl
    # ---- combination ----------------------------------------------------------------------
    if iv and (re.search(r"combin|plus|\bwith\b|\+|together", q)) and (len(iv) >= 2 or cls):
        a = iv[0]
        b = cls[0] if cls else iv[1]
        return P("combination", f"Protocols combining {a.name} with {b.name}", answer_types=["Protocol"],
                 steps=[Step("combination", {**base, "a": a.id, "b": b.id}, "explicit COMBINED_WITH statements or shared-arm structure")])
    # ---- path / trace ------------------------------------------------------------------------
    if re.search(r"\btrace\b|\bpath\b|connect|link between|relationship between|how is .* related", q):
        if len(anchors) >= 2:
            a, b = anchors[0], anchors[1]
            return P("path_between", f"Relationship paths between {a.name} and {b.name}", answer_types=[b.type],
                     steps=[Step("path_between", {**base, "limit": 10, "a": a.id, "b": b.id, "rels": PATH_RELS}, "allShortestPaths <= 5 hops")])
        if iv:
            return P("trace_intervention", f"Trace {iv[0].name} through arms, protocols, populations and endpoints",
                     answer_types=["Endpoint", "StudyArm", "CancerSubtype", "StudyPopulation", "TreatmentSetting", "Document"],
                     steps=[Step("trace_intervention", {**base, "limit": min(limit, 15), "id": iv[0].id}, "multi-hop trace")])
    # ---- eligibility --------------------------------------------------------------------------
    if re.search(r"eligib|inclusion|exclusion|criteri", q):
        if bm and not iv:
            return P("biomarker_eligibility", f"Protocols using {bm[0].name} in eligibility criteria", answer_types=["EligibilityCriterion"],
                     steps=[Step("biomarker_eligibility", {**base, "per": 6, "id": bm[0].id}, "criterion-level biomarker links")])
        if iv:
            return P("eligibility_for_intervention", f"Eligibility criteria of protocols investigating {iv[0].name}",
                     answer_types=["EligibilityCriterion"],
                     steps=[Step("eligibility_for_intervention", {**base, "limit": min(limit, 12), "per": 40, "id": iv[0].id}, "criteria")])
        if prot:
            return P("eligibility_of_protocol", f"Eligibility criteria of {prot[0].name[:60]}", answer_types=["EligibilityCriterion"],
                     steps=[Step("eligibility_of_protocol", {**base, "id": prot[0].id}, "criteria")])
    # ---- mentions / context -------------------------------------------------------------------
    if re.search(r"\bmention|context|appear|where .* (discussed|described)", q) and anchors:
        x = anchors[0]
        return P("mention_context", f"Protocols mentioning {x.name} (mention only)", answer_types=["Document"],
                 steps=[Step("mention_context", {**base, "id": x.id}, "Document-MENTIONS edges")])
    # ---- most common ---------------------------------------------------------------------------
    if re.search(r"most (common|frequent)|top \d+|how many protocols", q) and not anchors:
        label, rel = ("Drug", "INVESTIGATES")
        if "biomarker" in q:
            label, rel = "Biomarker", "ASSOCIATED_WITH_BIOMARKER"
        elif "endpoint" in q:
            label, rel = "Endpoint", "HAS_PRIMARY_ENDPOINT"
        elif "subtype" in q or "disease" in q:
            label, rel = "CancerSubtype", "STUDIES"
        elif "adverse" in q:
            label, rel = "AdverseEvent", "MONITORS_ADVERSE_EVENT"
        return P("top_entities", f"Most frequent {label} entities ({rel})", answer_types=[label],
                 steps=[Step("top_entities", {**base, "per": 10, "rel": rel, "label": label}, "aggregate over protocols")])
    # ---- protocol overview ----------------------------------------------------------------------
    if prot and not (iv or cond or bm or ae or ep or cls):
        p = prot[0]
        if p.type == "ClinicalTrial":
            return P("entity_neighborhood", f"Protocol documents for registered trial {p.name}", answer_types=["Protocol"],
                     steps=[Step("entity_neighborhood", {**base, "per": 40, "id": p.id, "rels": PATH_RELS}, "versions of the trial")])
        return P("protocol_overview", f"Overview of {p.name[:80]}", answer_types=list(INTERVENTION | CONDITION | {"Endpoint", "Biomarker"}),
                 steps=[Step("protocol_overview", {**base, "per": 60, "id": p.id, "rels": OVERVIEW_RELS}, "clinical relationships")])
    # ---- default: which trials relate to X ----------------------------------------------------------
    cond_specific = [c for c in cond if c.id != "disease:breast-cancer"] or cond
    target = (iv or cls or cond_specific or bm or ep or ae or anchors or [None])[0]
    if target is None:
        return Plan("unsupported", "No indexed entity could be identified in the question", anchors,
                    notes=["Mention a drug, biomarker, subtype, endpoint, adverse event, NCT number or trial acronym."])
    tpl = ("trials_for_intervention" if target.type in INTERVENTION else "trials_for_class" if target.type == "DrugClass"
           else "trials_for_condition" if target.type in CONDITION else "trials_for_biomarker" if target.type == "Biomarker"
           else "trials_for_endpoint" if target.type == "Endpoint" else "trials_for_adverse_event" if target.type == "AdverseEvent"
           else "entity_neighborhood" if target.type in ("ClinicalTrial", "Sponsor", "MolecularTarget", "Assessment", "LaboratoryTest", "DiagnosticProcedure", "StatisticalMethod", "StudyDesign", "StudyPhase")
           else "trials_for_entity_generic")
    pl = P("trials_for_entity", f"Protocols related to {target.name} ({target.type})", answer_types=["Protocol"],
           steps=[Step(tpl, {**base, "id": target.id, **({"per": 60, "rels": PATH_RELS} if tpl == "entity_neighborhood" else {})},
                       f"{tpl} pattern")])
    # extra constraint: a second entity narrows the protocol set (e.g. "trastuzumab trials in TNBC")
    # "breast cancer" is the whole corpus - it never narrows results
    others = [a for a in anchors if a.id != target.id and a.id != "disease:breast-cancer"
              and a.type in CONDITION | {"Biomarker", "Endpoint"} | INTERVENTION]
    if others:
        pl.notes.append(f"Additional constraint applied: protocols must also relate to {', '.join(o.name for o in others[:2])}.")
        pl.traversal["constraints"] = [o.id for o in others[:2]]
    return pl
