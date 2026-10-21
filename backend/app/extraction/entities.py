"""Stage 5a - entity recognition and protocol metadata extraction (rule-based provider).

* Dictionary matching against the curated lexicon (longest match wins, word boundaries,
  hyphen/space tolerant). Ambiguous abbreviations are case-sensitive and context-checked.
* Document-local abbreviation learning: "Trastuzumab deruxtecan (T-DXd; AZD4552)" teaches
  this document that AZD4552 refers to trastuzumab deruxtecan.
* Drug-like terms that are not in the dictionary (INN suffixes, development codes) are
  returned as *candidates*; entity resolution decides whether they become provisional
  entities or go to human review. They are never silently merged.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.extraction import lexicon as L

BOUND_L = r"(?<![A-Za-z0-9])"
BOUND_R = r"(?![A-Za-z0-9])"


def norm(s: str) -> str:
    s = s.lower().replace("²", "2").replace("α", "alpha")
    s = re.sub(r"[‐-―\-]+", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,;:")


def _alias_pattern(alias: str) -> str:
    parts = re.split(r"[\s\-‐‑]+", alias.strip())
    return r"[\s\-‐‑]?".join(re.escape(p) for p in parts if p)


@dataclass
class Mention:
    concept_id: str
    type: str
    surface: str
    start: int
    end: int
    method: str  # lexicon | lexicon-cs | doc-abbrev | compact


class Matcher:
    def __init__(self, extra_cs: dict[str, str] | None = None):
        ci_alias: dict[str, set[str]] = defaultdict(set)
        cs_alias: dict[str, set[str]] = defaultdict(set)
        self.context: dict[str, re.Pattern] = {}
        self.neg_context: dict[str, re.Pattern] = {}
        for c in L.CONCEPTS:
            if c.type in ("MolecularTarget", "DrugClass", "StudyPhase"):
                continue
            names = {c.name} | set(c.aliases) if c.type not in ("CombinationTherapy",) else set(c.aliases)
            for a in names:
                if len(a) >= 3:
                    ci_alias[norm(a)].add(c.id)
            for a in c.cs_aliases:
                cs_alias[a].add(c.id)
            if c.context:
                self.context[c.id] = re.compile(c.context, re.I)
            if c.neg_context:
                self.neg_context[c.id] = re.compile(c.neg_context, re.I)
        for a, cid in (extra_cs or {}).items():
            cs_alias[a].add(cid)
        self.ci_lookup = ci_alias
        self.ci_compact: dict[str, set[str]] = defaultdict(set)
        for a, ids in ci_alias.items():
            self.ci_compact[re.sub(r"[\s\-]+", "", a)] |= ids
        self.cs_lookup = cs_alias
        ci_sorted = sorted(ci_alias, key=len, reverse=True)
        cs_sorted = sorted(cs_alias, key=len, reverse=True)
        self.ci_re = re.compile(BOUND_L + "(" + "|".join(_alias_pattern(a) for a in ci_sorted) + ")" + r"(?![A-Za-z0-9])", re.I)
        self.cs_re = re.compile(BOUND_L + "(" + "|".join(re.escape(a) for a in cs_sorted) + ")" + BOUND_R) if cs_sorted else None
        # compact (space-free) index for letter-spaced text layers
        self.compact = sorted(((re.sub(r"[^a-z0-9]", "", a), ids) for a, ids in ci_alias.items() if len(a) >= 7),
                              key=lambda x: -len(x[0]))

    def find(self, text: str) -> list[Mention]:
        out: list[Mention] = []
        taken: list[tuple[int, int]] = []

        def free(s, e):
            return all(e <= a or s >= b for a, b in taken)

        for m in self.ci_re.finditer(text):
            surf = m.group(1)
            key = norm(surf)
            ids = self.ci_lookup.get(key)
            if not ids:
                ids = self.ci_compact.get(re.sub(r"[\s\-]+", "", key))
            if not ids:
                continue
            for cid in ids:
                out.append(Mention(cid, L.BY_ID[cid].type, surf, m.start(1), m.end(1), "lexicon"))
            taken.append((m.start(1), m.end(1)))
        if self.cs_re:
            for m in self.cs_re.finditer(text):
                s, e = m.start(1), m.end(1)
                if not free(s, e):
                    continue
                for cid in self.cs_lookup[m.group(1)]:
                    ctx = self.context.get(cid)
                    if ctx is not None:
                        window = text[max(0, s - 60): e + 60]
                        window = window[: s - max(0, s - 60)] + " " + window[s - max(0, s - 60) + (e - s):]
                        if not ctx.search(window):
                            continue
                    neg = self.neg_context.get(cid)
                    if neg is not None and neg.search(text[max(0, s - 40): e + 40]):
                        continue
                    out.append(Mention(cid, L.BY_ID[cid].type, m.group(1), s, e, "lexicon-cs"))
                taken.append((s, e))
        if _letter_spaced(text):
            compact = re.sub(r"[^a-z0-9]", "", text.lower())
            seen = {m.concept_id for m in out}
            for key, ids in self.compact:
                if key in compact:
                    for cid in ids:
                        if cid not in seen:
                            out.append(Mention(cid, L.BY_ID[cid].type, key, -1, -1, "compact"))
                            seen.add(cid)
        out.sort(key=lambda m: m.start)
        return out


def _letter_spaced(text: str) -> bool:
    toks = text.split()
    return len(toks) >= 8 and sum(1 for t in toks if len(t) == 1 and t.isalpha()) / len(toks) > 0.2


@lru_cache(maxsize=1)
def base_matcher() -> Matcher:
    return Matcher()


# ---------------------------------------------------------------------------
# Document-local abbreviations
# ---------------------------------------------------------------------------
PAREN = re.compile(r"([A-Za-z][A-Za-z0-9\-/ ,.'+]{2,80}?)\s*\(([^()]{2,80})\)")
ABBR_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-+/.]{1,19}$")


def learn_doc_abbreviations(texts: list[str], matcher: Matcher) -> dict[str, str]:
    """Return {abbreviation: concept_id} learned from 'Full name (ABBR; CODE)' patterns."""
    found: dict[str, Counter] = defaultdict(Counter)
    for t in texts:
        for m in PAREN.finditer(t):
            left, inner = m.group(1), m.group(2)
            ms = [x for x in matcher.find(left) if x.end == len(left.rstrip()) or x.end >= len(left) - 1]
            if not ms:
                continue
            cid = ms[-1].concept_id
            if L.BY_ID[cid].type not in ("Drug", "Biomarker", "CancerSubtype", "Endpoint", "AdverseEvent"):
                continue
            for tok in re.split(r"[;,]|\bor\b|\balso known as\b", inner):
                tok = tok.strip()
                if not ABBR_TOKEN.match(tok) or tok.lower() in ("e.g", "i.e", "see", "na", "ref"):
                    continue
                if not any(ch.isupper() for ch in tok):
                    continue
                if norm(tok) in matcher.ci_lookup or tok in matcher.cs_lookup:
                    continue
                found[tok][cid] += 1
    return {abbr: c.most_common(1)[0][0] for abbr, c in found.items() if len(c) == 1}


# ---------------------------------------------------------------------------
# Unknown drug-like candidates
# ---------------------------------------------------------------------------
def drug_candidates(text: str, known_spans: list[tuple[int, int]]) -> list[tuple[str, int, int, str]]:
    out = []

    def overlaps(s, e):
        return any(not (e <= a or s >= b) for a, b in known_spans)

    for m in L.DRUG_SUFFIX.finditer(text):
        if not overlaps(m.start(1), m.end(1)):
            out.append((m.group(1), m.start(1), m.end(1), "inn-suffix"))
    for m in L.DRUG_CODE.finditer(text):
        code = m.group(1)
        if L.DRUG_CODE_STOP.match(code) or overlaps(m.start(1), m.end(1)):
            continue
        if re.fullmatch(r"[A-Z]{2,5}[- ]?(19|20)\d\d", code):  # years / guideline versions
            continue
        out.append((code, m.start(1), m.end(1), "dev-code"))
    return out


# ---------------------------------------------------------------------------
# Protocol metadata
# ---------------------------------------------------------------------------
NCT_RE = re.compile(r"NCT\s?0?\d{7,8}")
PHASE_RE = re.compile(r"\bphase\s*(I{1,3}V?|IV|[1-4])\s*([ab])?(?:\s*(?:/|-|and)\s*(I{1,3}|[1-4])\s*([ab])?)?\b", re.I)
ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4"}
DATE_RE = re.compile(
    r"(\d{1,2}[\s\-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?[\s\-,]+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", re.I)
VERSION_RE = re.compile(r"\b(?:Protocol\s+)?Version(?:\s+(?:No\.?|Number|#))?\s*[:#]?\s*(\d{1,2}(?:\.\d{1,2}){0,2})\b", re.I)
AMEND_RE = re.compile(r"\bAmendment(?:\s+(?:No\.?|Number|#))?\s*[:#]?\s*(\d{1,2}|[A-Z])\b(?!\s*(?:to|of)\b)", re.I)
SPONSOR_RE = re.compile(r"\bSponsor(?:\s+Name)?\s*[:\-]\s*(.{3,120})", re.I)
PROTO_CODE_RE = re.compile(r"\b(?:Protocol\s*(?:Number|No\.?|#|ID|Code|Identifier)|Study\s*(?:Code|Number|No\.?)|Sponsor\s+Protocol\s+(?:Number|No\.?))\s*[:#]?\s*([A-Z0-9][A-Za-z0-9\-_/.]{2,30})")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s: str) -> str | None:
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"(\d{1,2})[\s\-]([A-Za-z]{3})[a-z]*\.?[\s\-,]+(\d{4})", s)
    if m and m.group(2).lower() in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).lower() in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return None  # numeric d/m/y is ambiguous - keep the raw string only


def normalize_phase(m: re.Match) -> str:
    a = ROMAN.get(m.group(1).upper(), m.group(1))
    s = f"Phase {a}{(m.group(2) or '').lower()}"
    if m.group(3):
        b = ROMAN.get(m.group(3).upper(), m.group(3))
        s = f"Phase {a}/{b}"
    return s


def extract_metadata(extraction: dict[str, Any], chunks: list[dict], filename: str) -> dict[str, Any]:
    pages = extraction["pages"]
    first_text = "\n".join(l["text"] for p in pages[:8] for l in p["lines"])
    all_text_head = "\n".join(l["text"] for p in pages[:30] for l in p["lines"])
    meta: dict[str, Any] = {"evidence": {}}

    # NCT identifier of THIS trial: only accepted from the first pages or next to registry wording.
    # NCT numbers elsewhere are usually citations of other trials and must not be adopted.
    reg_cue = re.compile(r"clinicaltrials\.gov|registr|identifier|nct\s*(number|no|#|id)|trial id", re.I)
    cite_cue = re.compile(r"(trial|study)\s*\($|\bin the\b.{0,60}$", re.I)
    ncts: Counter = Counter()
    for pi, p in enumerate(pages):
        for l in p["lines"]:
            for m in NCT_RE.finditer(l["text"]):
                k = re.sub(r"\s", "", m.group(0))
                k = k if len(k) == 11 else "NCT" + k[3:].zfill(8)
                before = l["text"][:m.start()]
                if pi < 3 and not cite_cue.search(before):
                    ncts[k] += 3
                elif reg_cue.search(l["text"]) and not cite_cue.search(before):
                    ncts[k] += 2
    meta["nct_id"] = ncts.most_common(1)[0][0] if ncts else None
    meta["all_nct_ids"] = sorted({re.sub(r"\s", "", m.group(0)) for p in pages for l in p["lines"] for m in NCT_RE.finditer(l["text"])})

    # Title: largest-font text on page 1 (lines of that size merged), else PDF metadata
    title = ""
    if pages and pages[0]["lines"]:
        p0 = [l for l in pages[0]["lines"] if len(l["text"]) > 3 and not re.fullmatch(r"[\d\W]+", l["text"])]
        if p0:
            big = max(l["size"] for l in p0)
            tl = [l["text"] for l in p0 if abs(l["size"] - big) < 0.6]
            if len(" ".join(tl)) < 25:  # logo/short banner - take the next size down too
                sizes = sorted({round(l["size"], 1) for l in p0}, reverse=True)
                if len(sizes) > 1:
                    tl = [l["text"] for l in p0 if l["size"] >= sizes[1] - 0.3]
            title = " ".join(tl)[:400]
    if len(title) < 12 and extraction.get("pdf_title"):
        title = extraction["pdf_title"]
    meta["title"] = re.sub(r"\s+", " ", title).strip() or filename
    meta["short_name"] = re.sub(r"\.pdf$", "", filename, flags=re.I).strip()[:90]

    # Phase: most frequent mention in the first 30 pages
    phases = Counter(normalize_phase(m) for m in PHASE_RE.finditer(all_text_head))
    meta["phase"] = phases.most_common(1)[0][0] if phases else None
    meta["phase_counts"] = dict(phases)

    m = SPONSOR_RE.search(first_text)
    sponsor = None
    if m:
        sponsor = re.split(r"\s{2,}|,\s*\d|\bAddress\b|\bLegal\b", m.group(1).strip())[0].strip(" :;,.")
        if len(sponsor) < 3 or sponsor.lower().startswith(("name", "address", "information")):
            sponsor = None
    meta["sponsor"] = sponsor
    m = PROTO_CODE_RE.search(first_text)
    meta["sponsor_protocol_code"] = m.group(1) if m and not m.group(1).upper().startswith("NCT") else None

    versions = VERSION_RE.findall(first_text)
    meta["version_label"] = versions[0] if versions else None
    amends = [a for a in AMEND_RE.findall(first_text) if a != "0"]
    meta["amendment"] = max(amends, key=lambda a: int(a) if a.isdigit() else 0) if amends else None
    dates = []
    for line in first_text.splitlines()[:250]:
        if re.search(r"(version|amendment|protocol|date|effective|final)", line, re.I):
            for d in DATE_RE.findall(line):
                pd = parse_date(d)
                if pd:
                    dates.append(pd)
    meta["version_date"] = max(dates) if dates else None

    # refined in the pipeline once sections are known (an appended SAP => "protocol+sap")
    meta["document_type"] = "sap" if re.search(r"statistical analysis plan", meta["title"] + " " + first_text[:600], re.I) else "protocol"
    return meta
