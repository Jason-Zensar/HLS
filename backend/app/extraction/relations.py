"""Stage 5b - relationship (claim) extraction, rule-based provider.

Every clinically meaningful relationship is produced as an *ExtractedClaim* tied to the exact
evidence chunk, page range and supporting quote. Relationships are only asserted when the
protocol structure or an explicit sentence pattern supports them:

* Section semantics: a drug described in the synopsis / treatment / dosing / arms sections is
  INVESTIGATED by the protocol; the same drug mentioned only in background or in an exclusion
  criterion ("prior trastuzumab") is not - it becomes a criterion reference or a plain MENTION.
* Sentence patterns: COMBINED_WITH needs an explicit connector ("+", "plus", "in combination
  with"); COMPARED_WITH needs "versus"/"compared with"; Drug-adverse-event statements need
  reporting language in the same sentence and are never labelled causal.
* Co-occurrence alone never creates a clinical edge.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from app.extraction import lexicon as L
from app.extraction.entities import Matcher, Mention, drug_candidates, norm

SEC_WEIGHT = {
    "title_page": 0.9, "synopsis": 0.9, "dosing": 0.85, "treatment_arms": 0.88, "study_design": 0.85,
    "objectives": 0.85, "primary_endpoints": 0.9, "secondary_endpoints": 0.9, "exploratory_endpoints": 0.85,
    "endpoints": 0.85, "inclusion_criteria": 0.9, "exclusion_criteria": 0.9, "eligibility": 0.8,
    "schedule_of_assessments": 0.8, "study_procedures": 0.75, "safety_monitoring": 0.8, "adverse_events": 0.8,
    "statistics": 0.8, "biomarkers": 0.8, "follow_up": 0.8, "randomization": 0.8, "stratification": 0.8,
    "pharmacokinetics": 0.75, "discontinuation": 0.7, "concomitant_medications": 0.6, "background": 0.5,
    "unknown": 0.6, "appendix": 0.5, "amendments": 0.55, "ethics_administration": 0.4, "references": 0.2,
    "abbreviations": 0.3,
}
INV_SECTIONS = {"synopsis", "dosing", "treatment_arms", "study_design", "objectives", "primary_endpoints", "randomization"}
POP_SECTIONS = {"synopsis", "study_design", "objectives", "inclusion_criteria", "eligibility", "primary_endpoints"}
ENDPOINT_SECTIONS = {"primary_endpoints", "secondary_endpoints", "exploratory_endpoints", "endpoints", "objectives", "synopsis", "statistics"}
AE_SECTIONS = {"adverse_events", "safety_monitoring", "dosing", "discontinuation"}
ASSESS_SECTIONS = {"schedule_of_assessments", "study_procedures", "safety_monitoring", "follow_up", "biomarkers", "pharmacokinetics"}
BIOMARKER_SECTIONS = {"synopsis", "objectives", "biomarkers", "inclusion_criteria", "primary_endpoints", "secondary_endpoints",
                      "exploratory_endpoints", "endpoints", "study_design"}
SUPPORTIVE_CTX = re.compile(r"premedicat|pre-medicat|prophyla|antiemetic|anti-emetic|concomitant|rescue|supportive care|"
                            r"hypersensitivity reactions?.{0,30}(treated|manage)|prohibited|not permitted|allowed", re.I)
# "and", "," and "/" usually join alternatives ("paclitaxel, nab-paclitaxel or capecitabine"), so they are NOT connectors
COMBO_CONNECTOR = re.compile(r"^\s*(?:\([^)]{0,40}\)\s*)?,?\s*(\+|plus|in combination with|combined with|together with|administered with|given with|followed by)\s*(?:\([^)]{0,40}\)\s*)?$", re.I)
VERSUS_CONNECTOR = re.compile(r"^\s*(?:\([^)]{0,60}\)\s*)?,?\s*(vs\.?|versus|compared (?:with|to)|in comparison (?:with|to))\s*(?:\([^)]{0,40}\)\s*)?$", re.I)
AE_ASSOC = re.compile(r"associated with|has been (reported|observed|associated)|have been (reported|observed)|were reported|was reported|"
                      r"risk of|may cause|can cause|adverse (drug )?reactions?|toxicit|incidence of|occurred|events? of|"
                      r"identified risk|potential risk|known risk|warnings? and precautions|side effects?", re.I)
SAFETY_RULE = re.compile(r"discontinu|withh[oe]ld|interrupt|dose reduc|reduce the dose|permanently|delay(ed)? (the )?(dose|treatment)", re.I)
DOSE_RE = re.compile(r"(\d+(?:[.,]\d+)?(?:\s*(?:-|to|–)\s*\d+(?:[.,]\d+)?)?)\s*(mg/m2|mg/m²|mg/m\^2|mg/m 2|mg/kg|mcg/kg|µg/kg|mg|mcg|µg|g/m2|g|IU|units?|mL/kg|MBq|kBq/kg)\b", re.I)
AUC_RE = re.compile(r"\bAUC\s*(?:=|of)?\s*(\d+(?:\.\d+)?)", re.I)
FREQ_RE = re.compile(r"(once daily|twice daily|three times daily|daily|\bQD\b|\bBID\b|\bTID\b|\bq\s?\d+\s?(?:w|wk|weeks?|d|days?)\b|"
                     r"every\s+(?:\d+|one|two|three|four|six|eight|twelve)\s+(?:weeks?|days?|months?)|weekly|bi-?weekly|monthly|"
                     r"on days?\s+\d+(?:\s*(?:,|and|-|–|to|through)\s*\d+)*|days?\s+\d+\s*(?:-|–|to|through)\s*\d+|"
                     r"3 weeks on[/ ,]+1 week off|\d+ days on[/ ,]+\d+ days off|continuous(?:ly)?|single dose|loading dose|maintenance dose)", re.I)
CYCLE_RE = re.compile(r"(\d{1,2})[\s-]*(?:day|d)[\s-]*cycles?|cycles?\s+(?:of|are|is|will be)\s+(\d{1,2})\s+days|(?:each|one|1)\s+cycle\s*(?:=|is|consists of)\s*(\d{1,2})\s*days", re.I)
ARM_RE = re.compile(r"\b(?:(Arm|Cohort|Group|Part)\s+([A-Z]\d?|\d{1,2}[A-Za-z]?|[IVX]{1,4})\b|((?:Experimental|Control|Investigational|Comparator|Placebo|Treatment|Standard)\s+(?:arm|group|cohort)))", re.I)
FOLLOWUP_RE = re.compile(r"(every|each|q)\s*\d+\s*(weeks?|months?)|annually|yearly|every (three|six|twelve) months", re.I)
TARGET_PAT = re.compile(r"(anti[-\s]?|inhibitor of |targeting |directed against |binds? (?:to )?|antagonist of |degrader of |blocks? )", re.I)
INCL_MARK = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:key\s+)?inclusion criteria", re.I)
EXCL_MARK = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:key\s+)?exclusion criteria", re.I)
LEVEL_MARK = re.compile(r"\b(primary|secondary|exploratory|tertiary|key secondary)\b\s*(?:efficacy\s+)?(end ?points?|objectives?|outcomes?|outcome measures?|analys[ie]s|:)?", re.I)
SUBTYPE_IMPLIES = {
    "subtype:triple-negative-breast-cancer": ["biomarker:estrogen-receptor-er", "biomarker:progesterone-receptor-pgr", "biomarker:her2"],
    "subtype:her2-positive-breast-cancer": ["biomarker:her2"],
    "subtype:her2-low-breast-cancer": ["biomarker:her2-low-expression"],
    "subtype:hr-positive-her2-negative-breast-cancer": ["biomarker:hormone-receptor-hr-status", "biomarker:her2"],
    "subtype:hr-positive-her2-positive-breast-cancer": ["biomarker:hormone-receptor-hr-status", "biomarker:her2"],
}
INTERVENTION_TYPES = {"Drug", "Intervention", "CombinationTherapy"}
NEG_CTX = re.compile(r"(\bnever\b|\bnot\b|\bno\b|\bnon-|\bwithout\b|\bexclud\w*|\bother than\b|\bexcept\b|\brather than\b|\bineligible\b)[^.;]{0,35}$", re.I)
PRIOR_CTX = re.compile(r"(progress\w*|relaps\w*|recurr\w*)\s+(on|after|following|during|within)|prior|previous\w*|pre-?treated|"
                       r"refractory|resistant|failure of|after\s*$|following\s*$|post-?\s*$", re.I)


def h(*parts: Any) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans; never split inside decimals ("2.5 mg") or abbreviations like "vs." / "e.g."."""
    spans, start = [], 0
    for m in re.finditer(r"(?<!\bvs)(?<!\be\.g)(?<!\bi\.e)(?<!\bet al)(?<!\bNo)(?<!\d)[.;!?](?=\s+[A-Z(\[\d•-])|\n", text):
        end = m.end()
        if end - start > 3:
            spans.append((start, end))
        start = end
    if len(text) - start > 3:
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def quote_for(text: str, s: int, e: int, maxlen: int = 420) -> str:
    q = text[s:e].strip()
    if len(q) <= maxlen:
        return q
    return q[:maxlen].rsplit(" ", 1)[0] + " ..."


class DocExtractor:
    def __init__(self, doc_id: str, chunks: list[dict], meta: dict, matcher: Matcher):
        self.doc_id = doc_id
        self.pid = f"protocol:{doc_id}"
        self.chunks = chunks
        self.meta = meta
        self.matcher = matcher
        self.entities: dict[str, dict] = {}
        self.claims: list[dict] = []
        self.mentions: list[tuple[str, str, str, int]] = []
        self.candidates: list[dict] = []
        self._claim_keys: dict[tuple, dict] = {}

    # ------------------------------------------------------------------ helpers
    def entity(self, eid: str, etype: str, name: str, *, scope="canonical", labels=(), **props) -> str:
        if eid not in self.entities:
            self.entities[eid] = {"id": eid, "type": etype, "name": name, "labels": list(labels), "scope": scope,
                                  "props": props, "resolution_status": "resolved" if scope == "canonical" else "document"}
        else:
            self.entities[eid]["props"].update({k: v for k, v in props.items() if v is not None})
        return eid

    def concept_entity(self, cid: str) -> str:
        c = L.BY_ID[cid]
        return self.entity(cid, c.type, c.name, labels=c.extra_labels, method="lexicon", **{k: v for k, v in c.props.items() if k != "components"})

    def claim(self, predicate: str, subj: str, obj: str, chunk: dict, quote: str, *, method: str,
              assertion: str = "explicit", conf: float | None = None, max_evidence: int = 4, **qual) -> dict | None:
        """Aggregate claims per (predicate, subject, object): keep up to `max_evidence` passages."""
        key = (predicate, subj, obj)
        base = SEC_WEIGHT.get(chunk["section_category"], 0.6)
        if chunk["chunk_type"] in ("table", "table_row"):
            base *= 0.95
        base *= max(0.3, chunk.get("extraction_confidence") or 1.0)
        c = round(min(0.99, conf if conf is not None else base), 3)
        ev = {"chunk_id": chunk["id"], "page_start": chunk["page_start"], "page_end": chunk["page_end"],
              "quote": quote, "section": chunk["section_title"], "section_category": chunk["section_category"],
              "confidence": c}
        if key in self._claim_keys:
            cl = self._claim_keys[key]
            if len(cl["evidence"]) < max_evidence and all(e["chunk_id"] != chunk["id"] for e in cl["evidence"]):
                cl["evidence"].append(ev)
            cl["evidence_count"] += 1
            cl["confidence"] = round(max(cl["confidence"], c), 3)
            for k, v in qual.items():
                if v and k not in cl["qualifiers"]:
                    cl["qualifiers"][k] = v
            return cl
        cl = {"id": "clm_" + h(self.doc_id, predicate, subj, obj), "doc_id": self.doc_id, "predicate": predicate,
              "subject": subj, "object": obj, "method": method, "assertion_type": assertion, "confidence": c,
              "evidence": [ev], "evidence_count": 1, "qualifiers": {k: v for k, v in qual.items() if v}}
        self._claim_keys[key] = cl
        self.claims.append(cl)
        return cl

    # ------------------------------------------------------------------ main
    def run(self) -> dict[str, Any]:
        meta = self.meta
        self.entity(self.pid, "Protocol", meta.get("short_name") or meta.get("title") or self.doc_id, scope="document", doc_id=self.doc_id,
                    title=meta.get("title"),
                    nct_id=meta.get("nct_id"), phase=meta.get("phase"), sponsor=meta.get("sponsor"),
                    sponsor_protocol_code=meta.get("sponsor_protocol_code"), version_label=meta.get("version_label"),
                    version_date=meta.get("version_date"), amendment=meta.get("amendment"),
                    document_type=meta.get("document_type"))
        chunk_mentions: dict[str, list[Mention]] = {}
        title_mentions = self.matcher.find(meta.get("title") or "")
        crit_mode: str | None = None
        for ch in self.chunks:
            if ch["chunk_type"] == "toc" or ch["section_category"] in ("references", "abbreviations"):
                continue
            ms = self.matcher.find(ch["text"])
            chunk_mentions[ch["id"]] = ms
            for m in ms:
                self.mentions.append((m.concept_id, ch["id"], m.surface, ch["page_start"]))
            # unknown drug-like candidates in sections that describe study treatment
            if ch["section_category"] in INV_SECTIONS | {"title_page"} and ch["chunk_type"] != "table_row":
                spans = [(m.start, m.end) for m in ms]
                for surf, s, e, how in drug_candidates(ch["text"], spans):
                    a, b = sentences_around(ch["text"], s)
                    self.candidates.append({"surface": surf, "method": how, "chunk_id": ch["id"],
                                            "page": ch["page_start"], "section_category": ch["section_category"],
                                            "context": ch["text"][a:b][:300]})
            # eligibility criterion mode tracking (for documents without separate headings)
            cat = ch["section_category"]
            first = ch["text"][:80]
            if INCL_MARK.match(first):
                crit_mode = "inclusion"
            elif EXCL_MARK.match(first):
                crit_mode = "exclusion"
            if cat == "inclusion_criteria":
                crit_mode = "inclusion"
            elif cat == "exclusion_criteria":
                crit_mode = "exclusion"
            elif cat != "eligibility":
                crit_mode = None
            ch["_crit_mode"] = crit_mode

        self._title_claims(title_mentions)
        self._phase_claim()
        for ch in self.chunks:
            ms = chunk_mentions.get(ch["id"])
            if ms is None:
                continue
            self._section_claims(ch, ms)
            self._sentence_claims(ch, ms)
            if ch["_crit_mode"] and ch["chunk_type"] in ("list_item", "paragraph") and ch["section_category"] in (
                    "inclusion_criteria", "exclusion_criteria", "eligibility"):
                self._criterion(ch, ms, ch["_crit_mode"])
            if ch["section_category"] in INV_SECTIONS | {"title_page"}:
                self._arms(ch, ms)
            if ch["section_category"] in {"dosing", "treatment_arms", "synopsis", "study_design"}:
                self._dosing(ch, ms)
            if ch["section_category"] == "follow_up":
                self._follow_up(ch)
            if ch["section_category"] in {"safety_monitoring", "dosing", "adverse_events", "discontinuation"}:
                self._safety_rules(ch, ms)
        self._finalize_investigates()
        return {"entities": list(self.entities.values()), "claims": self.claims, "mentions": self.mentions,
                "candidates": self.candidates}

    # ------------------------------------------------------------------ rules
    def _title_claims(self, ms: list[Mention]):
        title = self.meta.get("title") or ""
        if not title:
            return
        front = next((c for c in self.chunks if c["page_start"] <= 2 and title[:30].lower() in c["text"].lower()), None)             or next((c for c in self.chunks if c["page_start"] == 1 and c["chunk_type"] != "toc"), None)
        pseudo = front or {"id": None, "page_start": 1, "page_end": 1, "section_title": "Title page",
                           "section_category": "title_page", "chunk_type": "paragraph", "extraction_confidence": 1.0}
        for m in ms:
            cid = m.concept_id
            t = L.BY_ID[cid].type
            self.concept_entity(cid)
            q = quote_for(title, 0, len(title))
            if t in INTERVENTION_TYPES:
                if PRIOR_CTX.search(title[max(0, m.start - 45): m.start]):
                    continue  # "progressed on endocrine therapy" describes prior treatment, not the study treatment
                self._inv[cid].append((pseudo, q, 0.95, "title"))
            elif t in ("CancerSubtype", "Disease"):
                self.claim("STUDIES", self.pid, cid, pseudo, q, method="rule:title", conf=0.95)
            elif t == "TreatmentSetting":
                self.claim("HAS_SETTING", self.pid, cid, pseudo, q, method="rule:title", conf=0.93)
            elif t == "StudyPopulation":
                self.claim("HAS_POPULATION", self.pid, cid, pseudo, q, method="rule:title", conf=0.93)
            elif t == "StudyDesign":
                self.claim("HAS_DESIGN", self.pid, cid, pseudo, q, method="rule:title", conf=0.95)
            elif t == "Biomarker":
                self.claim("ASSOCIATED_WITH_BIOMARKER", self.pid, cid, pseudo, q, method="rule:title", conf=0.92, role="title")

    def _phase_claim(self):
        ph = self.meta.get("phase")
        if not ph:
            return
        pid = f"phase:{L.slug(ph)}"
        self.entity(pid, "StudyPhase", ph)
        rx = re.compile(r"\bphase\s*(I{1,3}V?|IV|[1-4])", re.I)
        for ch in self.chunks[:400]:
            m = rx.search(ch["text"])
            if m and ch["chunk_type"] != "toc":
                a, b = sentences_around(ch["text"], m.start())
                self.claim("HAS_PHASE", self.pid, pid, ch, quote_for(ch["text"], a, b), method="rule:metadata",
                           conf=0.9, counts=str(self.meta.get("phase_counts")))
                return

    @property
    def _inv(self) -> dict[str, list]:
        if not hasattr(self, "_inv_store"):
            self._inv_store = defaultdict(list)
        return self._inv_store

    def _section_claims(self, ch: dict, ms: list[Mention]):
        cat = ch["section_category"]
        text = ch["text"]
        sents = sentences(text)
        for m in ms:
            cid, t = m.concept_id, m.type
            if m.start >= 0:
                a, b = next(((x, y) for x, y in sents if x <= m.start < y), (0, len(text)))
            else:
                a, b = 0, min(len(text), 400)
            q = quote_for(text, a, b)
            sent = text[a:b]
            negated = m.start >= 0 and bool(NEG_CTX.search(text[max(a, m.start - 45): m.start]))
            if negated and t in ("CancerSubtype", "Disease", "TreatmentSetting", "StudyPopulation", "Biomarker", "StudyDesign"):
                continue  # "never previously HER2-positive" must not make the protocol a HER2-positive study
            if t in INTERVENTION_TYPES and cat in INV_SECTIONS:
                if not SUPPORTIVE_CTX.search(sent):
                    has_dose = bool(DOSE_RE.search(sent) or AUC_RE.search(sent))
                    self._inv[cid].append((ch, q, None, "dose" if has_dose else "section"))
            elif t in ("CancerSubtype", "Disease") and (cat in POP_SECTIONS and ch.get("_crit_mode") != "exclusion"):
                self.concept_entity(cid)
                self.claim("STUDIES", self.pid, cid, ch, q, method="rule:section", min_needed=2)
                for imp in SUBTYPE_IMPLIES.get(cid, []):
                    if cat in ("inclusion_criteria", "synopsis", "eligibility", "objectives"):
                        self.concept_entity(imp)
                        self.claim("ASSOCIATED_WITH_BIOMARKER", self.pid, imp, ch, q, method="rule:subtype-implies",
                                   assertion="normalized", role="population definition (via subtype)", conf=0.7)
            elif t == "TreatmentSetting" and cat in POP_SECTIONS and ch.get("_crit_mode") != "exclusion":
                self.concept_entity(cid)
                self.claim("HAS_SETTING", self.pid, cid, ch, q, method="rule:section", min_needed=2)
            elif t == "StudyPopulation" and cat in POP_SECTIONS and ch.get("_crit_mode") != "exclusion":
                self.concept_entity(cid)
                self.claim("HAS_POPULATION", self.pid, cid, ch, q, method="rule:section", min_needed=2)
            elif t == "StudyDesign" and cat in {"synopsis", "study_design", "title_page", "randomization"}:
                self.concept_entity(cid)
                self.claim("HAS_DESIGN", self.pid, cid, ch, q, method="rule:section", min_needed=2)
            elif t == "Biomarker" and cat in BIOMARKER_SECTIONS:
                role = ("eligibility" if cat in ("inclusion_criteria",) or ch.get("_crit_mode") == "inclusion"
                        else "biomarker analysis" if cat == "biomarkers" else "objective/endpoint" if "endpoint" in cat or cat == "objectives"
                        else "study description")
                self.concept_entity(cid)
                self.claim("ASSOCIATED_WITH_BIOMARKER", self.pid, cid, ch, q, method="rule:section", role=role, min_needed=2)
            elif t == "Endpoint" and cat in ENDPOINT_SECTIONS:
                self._endpoint(ch, m, q)
            elif t == "AdverseEvent" and cat in AE_SECTIONS:
                self.concept_entity(cid)
                self.claim("MONITORS_ADVERSE_EVENT", self.pid, cid, ch, q, method="rule:section", assertion="explicit")
            elif t in ("Assessment", "LaboratoryTest", "DiagnosticProcedure") and (cat in ASSESS_SECTIONS or ch["chunk_type"] == "table_row" and cat in ASSESS_SECTIONS | {"synopsis"}):
                self.concept_entity(cid)
                self.claim("REQUIRES_ASSESSMENT", self.pid, cid, ch, q, method="rule:section")
            elif t == "StatisticalMethod" and cat in ("statistics", "synopsis"):
                self.concept_entity(cid)
                self.claim("USES_STATISTICAL_METHOD", self.pid, cid, ch, q, method="rule:section")

    def _endpoint(self, ch: dict, m: Mention, q: str):
        cat = ch["section_category"]
        text = ch["text"]
        level = {"primary_endpoints": "primary", "secondary_endpoints": "secondary", "exploratory_endpoints": "exploratory"}.get(cat)
        # nearest preceding level marker in the same chunk overrides the section default
        if re.search(r"rationale|justification|background", ch["section_title"] or "", re.I):
            return  # discussion of why endpoints were chosen is not the endpoint definition
        before = text[max(0, m.start - 220): m.start] if m.start >= 0 else ""
        if cat in ("statistics", "synopsis") and m.start >= 0:
            sa, _ = sentences_around(text, m.start)
            before = text[sa:m.start]  # label must be in the same sentence here
        marks = list(LEVEL_MARK.finditer(before))
        if marks:
            word = marks[-1].group(1).lower()
            level = "secondary" if "secondary" in word else "exploratory" if word in ("exploratory", "tertiary") else "primary"
        if cat in ("synopsis", "statistics", "objectives", "endpoints") and level is None:
            return  # unlabelled endpoint mention outside an endpoint section: not asserted
        pred = {"primary": "HAS_PRIMARY_ENDPOINT", "secondary": "HAS_SECONDARY_ENDPOINT",
                "exploratory": "HAS_EXPLORATORY_ENDPOINT"}.get(level or "", "MEASURES_ENDPOINT")
        self.concept_entity(m.concept_id)
        self.claim(pred, self.pid, m.concept_id, ch, q, method="rule:endpoint-section" if not marks else "rule:endpoint-label")

    def _sentence_claims(self, ch: dict, ms: list[Mention]):
        cat = ch["section_category"]
        text = ch["text"]
        if not ms or ms[0].start < 0:
            return
        for a, b in sentences(text):
            sm = [m for m in ms if a <= m.start < b]
            ivs = [m for m in sm if m.type in INTERVENTION_TYPES]
            # combinations / comparisons (adjacent intervention mentions with an explicit connector)
            if len(ivs) >= 2 and cat in INV_SECTIONS | {"title_page", "background"} and ch["chunk_type"] != "table_row":
                for x, y in zip(ivs, ivs[1:]):
                    if x.concept_id == y.concept_id:
                        continue
                    between = text[x.end:y.start]
                    if len(between) > 45:
                        continue
                    if VERSUS_CONNECTOR.match(between):
                        self._pair("COMPARED_WITH", x, y, ch, quote_for(text, a, b), cat)
                    elif COMBO_CONNECTOR.match(between) and not re.search(r"\b(or|vs\.?|versus)\b", between, re.I):
                        if re.search(r"followed by", between, re.I):
                            self._pair("FOLLOWED_BY", x, y, ch, quote_for(text, a, b), cat)
                        else:
                            self._pair("COMBINED_WITH", x, y, ch, quote_for(text, a, b), cat)
            # drug -> adverse event statements
            aes = [m for m in sm if m.type == "AdverseEvent"]
            drugs = [m for m in sm if m.type == "Drug"]
            if aes and drugs and len(drugs) <= 3 and b - a < 600 and AE_ASSOC.search(text[a:b]) \
                    and cat in AE_SECTIONS | {"background", "safety_monitoring"}:
                for d in drugs:
                    for e in aes:
                        self.concept_entity(d.concept_id)
                        self.concept_entity(e.concept_id)
                        self.claim("ASSOCIATED_ADVERSE_EVENT", d.concept_id, e.concept_id, ch, quote_for(text, a, b),
                                   method="rule:ae-statement", assertion="protocol_statement", protocol_id=self.pid)
            # drug -> molecular target ("pembrolizumab, a humanized anti-PD-1 antibody")
            for d in drugs:
                tail = text[d.end: min(b, d.end + 160)]
                app = re.match(r"^\s*(?:\([^)]{0,60}\)\s*)?,?\s*(?:is\s+|which is\s+)?(?:a|an)(.{0,110})", tail, re.I | re.S)
                if not app:
                    continue
                desc = app.group(1).lower()
                for c in L.CONCEPTS:
                    if c.type != "MolecularTarget":
                        continue
                    hit = False
                    for al in [c.name.lower(), *c.aliases]:
                        al = re.escape(al.lower())
                        if re.search(rf"(anti-?\s?{al}|(inhibitor|antagonist|degrader) of (the )?{al}|targeting (the )?{al}|"
                                     rf"directed against (the )?{al}|{al}[- ](targeted|directed|inhibitor|antagonist|degrader|blocking|antibody))", desc):
                            hit = True
                            break
                    if hit:
                        self.concept_entity(d.concept_id)
                        self.entity(c.id, "MolecularTarget", c.name)
                        self.claim("TARGETS", d.concept_id, c.id, ch, quote_for(text, a, b), method="rule:target-appositive",
                                   protocol_id=self.pid)

    def _pair(self, pred: str, x: Mention, y: Mention, ch: dict, q: str, cat: str):
        self.concept_entity(x.concept_id)
        self.concept_entity(y.concept_id)
        a, b = (x.concept_id, y.concept_id) if pred != "COMBINED_WITH" or x.concept_id < y.concept_id else (y.concept_id, x.concept_id)
        bg = cat in ("background", "unknown", "appendix")
        self.claim(pred, a, b, ch, q, method="rule:connector", protocol_id=self.pid,
                   assertion="background_statement" if bg else "explicit", conf=0.45 if bg else None,
                   context="background / literature discussion" if bg else "study treatment description")
        if not bg:
            for m in (x, y):
                self._inv[m.concept_id].append((ch, q, None, "combination"))

    def _finalize_investigates(self):
        for cid, evs in self._inv.items():
            title = [e for e in evs if e[3] == "title"]
            dosed = [e for e in evs if e[3] == "dose"]
            n_chunks = len({e[0]["id"] for e in evs if e[0].get("id")})
            if not (title or dosed or n_chunks >= 2):
                continue
            self.concept_entity(cid)
            role = "named in protocol title" if title else "study treatment (dose specified)" if dosed else "study treatment"
            ordered = title + dosed + [e for e in evs if e[3] not in ("title", "dose")]
            for ch, q, conf, how in ordered[:6]:
                self.claim("INVESTIGATES", self.pid, cid, ch, q, method=f"rule:{how}", conf=conf, role=role)
        # claims that required at least two passages
        keep = []
        for cl in self.claims:
            if cl["qualifiers"].pop("min_needed", None) and cl["evidence_count"] < 2 and not str(cl["method"]).startswith("rule:title"):
                del self._claim_keys[(cl["predicate"], cl["subject"], cl["object"])]
                continue
            keep.append(cl)
        self.claims = keep

    def _criterion(self, ch: dict, ms: list[Mention], mode: str):
        text = ch["text"].strip()
        if len(text) < 15 or text.endswith(":") and len(text) < 120 or INCL_MARK.match(text) or EXCL_MARK.match(text):
            return
        etype = "InclusionCriterion" if mode == "inclusion" else "ExclusionCriterion"
        num = re.match(r"^(\d{1,2})\.", text)
        cid = f"crit:{self.doc_id}:{h(ch['id'])}"
        self.entity(cid, etype, (f"{'IC' if mode == 'inclusion' else 'EC'} {num.group(1)}: " if num else "") + text[:90],
                    scope="document", labels=["EligibilityCriterion"], text=text[:2000], number=num.group(1) if num else None,
                    page=ch["page_start"], chunk_id=ch["id"], protocol_id=self.pid)
        pred = "HAS_INCLUSION_CRITERION" if mode == "inclusion" else "HAS_EXCLUSION_CRITERION"
        self.claim(pred, self.pid, cid, ch, quote_for(text, 0, len(text), 600), method="rule:eligibility-list", conf=0.9)
        for m in ms:
            if m.start < 0:
                continue
            q = quote_for(text, *sentences_around(text, m.start))
            if m.type == "Biomarker":
                self.concept_entity(m.concept_id)
                self.claim("ASSOCIATED_WITH_BIOMARKER", cid, m.concept_id, ch, q, method="rule:criterion-mention")
            elif m.type in ("CancerSubtype", "Disease", "TreatmentSetting", "StudyPopulation", "AdverseEvent"):
                self.concept_entity(m.concept_id)
                neg = bool(NEG_CTX.search(text[max(0, m.start - 45): m.start]))
                self.claim("REFERENCES_CONDITION", cid, m.concept_id, ch, q, method="rule:criterion-mention",
                           polarity="negated" if neg else "affirmed")
                if m.type in ("CancerSubtype",):
                    for imp in SUBTYPE_IMPLIES.get(m.concept_id, []):
                        self.concept_entity(imp)
                        self.claim("ASSOCIATED_WITH_BIOMARKER", cid, imp, ch, q, method="rule:subtype-implies",
                                   assertion="normalized", conf=0.7)
            elif m.type in INTERVENTION_TYPES:
                self.concept_entity(m.concept_id)
                self.claim("REFERENCES_DRUG", cid, m.concept_id, ch, q, method="rule:criterion-mention")
            elif m.type in ("Assessment", "LaboratoryTest", "DiagnosticProcedure"):
                self.concept_entity(m.concept_id)
                self.claim("REQUIRES_ASSESSMENT", cid, m.concept_id, ch, q, method="rule:criterion-mention")

    def _arms(self, ch: dict, ms: list[Mention]):
        text = ch["text"]
        hits = list(ARM_RE.finditer(text))
        for i, m in enumerate(hits):
            label = (f"{m.group(1).title()} {m.group(2).upper()}" if m.group(1) else m.group(3).title()).strip()
            if label.lower().startswith("part") and not re.search(r"arm|cohort", text[m.end(): m.end() + 80], re.I):
                continue
            end = hits[i + 1].start() if i + 1 < len(hits) else min(len(text), m.end() + 260)
            window = text[m.start(): min(end, m.end() + 260)]
            arm_ms = [x for x in ms if m.start() <= x.start < m.start() + len(window) and x.type in INTERVENTION_TYPES]
            if not arm_ms:
                continue
            aid = f"arm:{self.doc_id}:{L.slug(label)}"
            self.entity(aid, "StudyArm", label, scope="document", description=window[:400], protocol_id=self.pid,
                        page=ch["page_start"])
            self.claim("INCLUDES_ARM", self.pid, aid, ch, quote_for(window, 0, len(window)), method="rule:arm-label")
            for x in arm_ms:
                if SUPPORTIVE_CTX.search(text[max(0, x.start - 60): x.end + 60]):
                    continue
                self.concept_entity(x.concept_id)
                self.claim("USES_INTERVENTION", aid, x.concept_id, ch, quote_for(window, 0, len(window)), method="rule:arm-window")
                self._inv[x.concept_id].append((ch, quote_for(window, 0, len(window)), None, "arm"))

    def _dosing(self, ch: dict, ms: list[Mention]):
        text = ch["text"]
        cyc = CYCLE_RE.search(text)
        if cyc:
            days = next(g for g in cyc.groups() if g)
            if 5 <= int(days) <= 84:
                tid = f"cycle:{self.doc_id}:{days}d"
                self.entity(tid, "TreatmentCycle", f"{days}-day cycle", scope="document", length_days=int(days), protocol_id=self.pid)
                a, b = sentences_around(text, cyc.start())
                self.claim("HAS_TREATMENT_CYCLE", self.pid, tid, ch, quote_for(text, a, b), method="rule:cycle-pattern")
        drugs = [m for m in ms if m.type == "Drug" and m.start >= 0]
        routes = [m for m in ms if m.type == "RouteOfAdministration"]
        for i, d in enumerate(drugs):
            nxt = drugs[i + 1].start if i + 1 < len(drugs) else len(text)
            seg_end = min(nxt, d.end + 160)
            seg = text[d.end:seg_end]
            dm = DOSE_RE.search(seg)
            am = AUC_RE.search(seg)
            if not dm and not am:
                continue
            if dm and am:
                dm_first = dm.start() <= am.start()
                am = None if dm_first else am
                dm = dm if dm_first else None
            a, b = sentences_around(text, d.start)
            sent = text[a:b]
            if SUPPORTIVE_CTX.search(sent) and L.BY_ID[d.concept_id].classes and \
                    L.CLASS_ID["supportive"] in L.BY_ID[d.concept_id].classes:
                continue
            if dm:
                value, unit = dm.group(1).replace(",", "."), dm.group(2).replace("²", "2").replace("^2", "2").replace("m 2", "m2")
                tail = seg[dm.end(): dm.end() + 120]
            else:
                value, unit = am.group(1), "AUC"
                tail = seg[am.end(): am.end() + 120]
            fm = FREQ_RE.search(tail) or FREQ_RE.search(sent)
            freq = fm.group(0).strip() if fm else None
            route = next((r for r in routes if a <= r.start < b), None)
            norm_key = f"{value}{unit.lower()}|{(freq or '').lower()}|{route.concept_id if route else ''}"
            did = f"dose:{self.doc_id}:{d.concept_id.split(':')[1]}:{h(norm_key)[:8]}"
            label = f"{L.BY_ID[d.concept_id].name} {value} {unit}" + (f" {freq}" if freq else "") + \
                    (f" {L.BY_ID[route.concept_id].name}" if route else "")
            self.concept_entity(d.concept_id)
            self.entity(did, "DoseSpecification", label, scope="document", drug_id=d.concept_id, dose_value=value,
                        dose_unit=unit, frequency=freq, route=L.BY_ID[route.concept_id].name if route else None,
                        protocol_id=self.pid, text=quote_for(text, a, b), page=ch["page_start"])
            q = quote_for(text, a, b)
            self.claim("HAS_DOSE_SPECIFICATION", self.pid, did, ch, q, method="rule:dose-pattern")
            self.claim("DOSE_OF", did, d.concept_id, ch, q, method="rule:dose-pattern")
            if route:
                self.concept_entity(route.concept_id)
                self.claim("ADMINISTERED_VIA", did, route.concept_id, ch, q, method="rule:dose-pattern")
            self._inv[d.concept_id].append((ch, q, None, "dose"))

    def _follow_up(self, ch: dict):
        text = ch["text"]
        for a, b in sentences(text):
            sent = text[a:b]
            if re.search(r"follow", sent, re.I) and FOLLOWUP_RE.search(sent) and len(sent) < 500:
                fid = f"fu:{self.doc_id}:{h(norm(sent))[:10]}"
                self.entity(fid, "FollowUpProcedure", sent.strip()[:90], scope="document", text=sent.strip()[:600],
                            protocol_id=self.pid, page=ch["page_start"])
                self.claim("HAS_FOLLOW_UP", self.pid, fid, ch, quote_for(text, a, b), method="rule:follow-up-pattern")

    def _safety_rules(self, ch: dict, ms: list[Mention]):
        text = ch["text"]
        if len([c for c in self.claims if c["predicate"] == "HAS_SAFETY_RULE"]) >= 60:
            return
        for a, b in sentences(text):
            sent = text[a:b]
            aes = [m for m in ms if a <= m.start < b and m.type == "AdverseEvent"]
            if not aes or not SAFETY_RULE.search(sent) or len(sent) > 600:
                continue
            rid = f"rule:{self.doc_id}:{h(norm(sent))[:10]}"
            self.entity(rid, "SafetyMonitoringRule", sent.strip()[:90], scope="document", text=sent.strip()[:600],
                        protocol_id=self.pid, page=ch["page_start"])
            q = quote_for(text, a, b)
            self.claim("HAS_SAFETY_RULE", self.pid, rid, ch, q, method="rule:safety-action")
            for e in aes:
                self.concept_entity(e.concept_id)
                self.claim("MONITORS_ADVERSE_EVENT", rid, e.concept_id, ch, q, method="rule:safety-action")


def sentences_around(text: str, pos: int) -> tuple[int, int]:
    for a, b in sentences(text):
        if a <= pos < b:
            return a, b
    return max(0, pos - 150), min(len(text), pos + 250)


def extract_document(doc_id: str, chunks: list[dict], meta: dict, matcher: Matcher) -> dict[str, Any]:
    return DocExtractor(doc_id, chunks, meta, matcher).run()
