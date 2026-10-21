"""Stage 3 - clinical document structure recognition.

Strategy (in order of reliability):
1. The PDF's embedded outline (table of contents) when it has enough entries.
2. Layout heuristics: numbered headings ("5.1 Inclusion Criteria", also when the number
   and title sit on separate lines), bold / larger-than-body short lines, ALL-CAPS headings.
Printed table-of-contents pages (dot leaders) are detected and excluded.

Each section title is then classified into a clinical category using contextual keyword
rules. Sub-sections without their own match inherit the parent's category and are flagged
as "inherited"; titles with no reliable match are left as "unknown".
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

# Ordered: first match wins, so more specific categories come first.
SECTION_CATEGORIES: list[tuple[str, str]] = [
    ("inclusion_criteria", r"\binclusion\b|\beligibility criteria\b.*\binclu|\bkey inclusion\b"),
    ("exclusion_criteria", r"\bexclusion\b"),
    ("eligibility", r"\beligib|\bselection of (study )?(population|patients|subjects|participants)|participant selection|patient selection|subject selection|study population|screen failure|lifestyle (considerations|restrictions)|enrollment criteria|entry criteria"),
    ("schedule_of_assessments", r"schedule of (assessments|activities|events|evaluations)|study calendar|time and events|study flow ?chart|soa\b"),
    ("primary_endpoints", r"primary (endpoint|end point|outcome|efficacy endpoint)"),
    ("secondary_endpoints", r"secondary (endpoint|end point|outcome)"),
    ("exploratory_endpoints", r"exploratory (endpoint|end point|outcome|objective)|tertiary"),
    ("endpoints", r"\bendpoints?\b|\bend points?\b|outcome measures?|objectives? and (endpoints|end points)|estimand"),
    ("objectives", r"\bobjectives?\b|\baims?\b|hypothes[ie]s"),
    ("synopsis", r"synopsis|protocol summary|study summary|executive summary|schema\b|study schema|trial summary"),
    ("discontinuation", r"discontinu|withdrawal|lost to follow"),
    ("dosing", r"\bdos(e|ing|age)\b|administration|dose modification|dose (reduction|delay|escalation)|treatment plan|study drug|investigational (medicinal )?product|study intervention|study treatment|treatment administration|drug information|pharmaceutical information|agent information"),
    ("treatment_arms", r"\barms?\b|\bcohorts?\b|treatment groups?|study (arms|groups)|treatment regimen"),
    ("randomization", r"randomi[sz]ation|treatment assignment|allocation|blinding"),
    ("stratification", r"stratif"),
    ("study_design", r"study design|overall design|trial design|design of (the )?study|investigational plan|methodology|study plan"),
    ("safety_monitoring", r"safety (monitoring|assessments?|considerations|reporting)|data (and )?safety monitoring|toxicit|stopping rules|dsmb|idmc|data monitoring committee"),
    ("adverse_events", r"adverse (event|reaction|experience)|\bsaes?\b|serious adverse|side effects|expected toxicities|pharmacovigilance"),
    ("biomarkers", r"biomarker|correlative|translational|genomic|pharmacogenomic|tissue (collection|samples)|biospecimen|ctdna|liquid biopsy"),
    ("pharmacokinetics", r"pharmacokinetic|\bpk\b|pharmacodynamic|immunogenicity"),
    ("statistics", r"statistic|sample size|analysis (population|set)s?|power calculation|interim analys|data analysis|analysis plan|efficacy analys|safety analys|missing data"),
    ("follow_up", r"follow[- ]?up|survival status|post[- ]treatment|end of (study|treatment)|long[- ]term"),
    ("concomitant_medications", r"concomitant|prohibited (medication|therap)|permitted (medication|therap)|prior and concomitant"),
    ("background", r"background|introduction|rationale|disease overview|scientific justification|benefit[- /]risk"),
    ("study_procedures", r"study (procedures|assessments|visits)|assessments? and procedures|screening|efficacy assessments?|tumou?r assessments?|response (criteria|evaluation|assessment)|recist|measurement of effect|laboratory"),
    ("amendments", r"amendment|summary of changes|protocol (history|revision)|document history|revision history|version history"),
    ("ethics_administration", r"ethic|informed consent|regulatory|administrative|publication policy|data (handling|management)|record keeping|quality (control|assurance)|monitoring of the study|confidentiality|investigator (obligations|responsibilit)|signature|approval page"),
    ("references", r"^references?$|bibliograph|literature cited"),
    ("appendix", r"^appendix|^appendices|^annex|^attachment"),
    ("abbreviations", r"abbreviation|definitions of terms|glossary|list of (tables|figures)"),
    ("title_page", r"^title page$|^cover page$"),
]
_CAT_RE = [(c, re.compile(p, re.I)) for c, p in SECTION_CATEGORIES]

NUM_HEADING = re.compile(r"^((?:\d{1,2}\.){0,4}\d{1,2})\.?\s+([A-Za-z][^\n]{1,140})$")
NUM_ONLY = re.compile(r"^((?:\d{1,2}\.){0,4}\d{1,2})\.?$")
APPENDIX = re.compile(r"^(appendix|annex|attachment)\s+[\w\d.-]+", re.I)
DOT_LEADER = re.compile(r"(\.{4,}|…{2,}|(\.\s){4,})[\s\d]*$")


_CAT_COMPACT = [(c, re.compile(re.sub(r"\\b|\s|\[- \]\?|\[- /\]|\^|\$", "", p), re.I)) for c, p in SECTION_CATEGORIES]


def classify_title(title: str) -> str:
    t = title.strip()
    for cat, rx in _CAT_RE:
        if rx.search(t):
            return cat
    # letter-spaced titles ("A D V E R S E  E V E N T S"): match on the de-spaced form
    toks = t.split()
    if toks and sum(1 for x in toks if len(x) <= 2) / len(toks) > 0.4:
        compact = re.sub(r"[^a-z0-9/]", "", t.lower())
        for cat, rx in _CAT_COMPACT:
            if rx.search(compact):
                return cat
    return "unknown"


def _sid(doc_id: str, ord_: int, title: str) -> str:
    return "sec_" + hashlib.sha1(f"{doc_id}|{ord_}|{title}".encode()).hexdigest()[:16]


def body_font_size(pages: list[dict]) -> float:
    c: Counter[float] = Counter()
    for p in pages:
        for l in p["lines"]:
            c[round(l["size"])] += len(l["text"])
    return float(c.most_common(1)[0][0]) if c else 10.0


def toc_pages(pages: list[dict]) -> set[int]:
    out = set()
    for p in pages:
        ls = p["lines"]
        if len(ls) < 6:
            continue
        dl = sum(1 for l in ls if DOT_LEADER.search(l["text"]))
        head = " ".join(l["text"].lower() for l in ls[:4])
        if dl / len(ls) > 0.25 or (dl >= 4 and ("contents" in head or "table of contents" in head)):
            out.add(p["page"])
    return out


def _in_tables(line: dict, tables: list[dict]) -> bool:
    x0, y0, x1, y1 = line["bbox"]
    cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
    for t in tables:
        a, b, c, d = t["bbox"]
        if a - 1 <= cx <= c + 1 and b - 1 <= cy <= d + 1:
            return True
    return False


def detect_structure(doc_id: str, extraction: dict[str, Any]) -> dict[str, Any]:
    pages = extraction["pages"]
    body = body_font_size(pages)
    tocp = toc_pages(pages)

    # Flatten lines with stable addresses (page index, line index)
    flat: list[tuple[int, int, dict]] = []
    for pi, p in enumerate(pages):
        for li, l in enumerate(p["lines"]):
            l["in_table"] = _in_tables(l, p["tables"])
            l["toc_page"] = p["page"] in tocp
            flat.append((pi, li, l))

    headings: list[dict] = []  # {pos, number, title, level, detection}
    toc = [e for e in extraction.get("toc", []) if e[2] and e[2] > 0 and e[1].strip()]
    used_toc = len(toc) >= 5
    if used_toc:
        headings = _headings_from_toc(toc, pages, flat)
    else:
        headings = _headings_from_layout(flat, body)

    # Build section records
    sections: list[dict] = []
    line_section: dict[tuple[int, int], str] = {}
    root_id = _sid(doc_id, -1, "front matter")
    sections.append({"id": root_id, "doc_id": doc_id, "parent_id": None, "number": "", "title": "Front matter",
                     "category": "title_page", "level": 0, "page_start": 1, "page_end": 1, "ord": 0,
                     "detection": "default"})
    stack: list[dict] = []
    head_by_pos = {h["pos"]: h for h in headings}
    current = sections[0]
    for idx, (pi, li, l) in enumerate(flat):
        h = head_by_pos.get(idx)
        if h:
            while stack and stack[-1]["level"] >= h["level"]:
                stack.pop()
            parent = stack[-1] if stack else None
            own = classify_title(h["title"])
            cat, det = own, h["detection"]
            if own == "unknown" and parent and parent["category"] not in ("unknown", "title_page"):
                cat, det = parent["category"], h["detection"] + "+inherited"
            sec = {"id": _sid(doc_id, len(sections), h["title"]), "doc_id": doc_id,
                   "parent_id": parent["id"] if parent else None, "number": h["number"], "title": h["title"],
                   "category": cat, "level": h["level"], "page_start": pages[pi]["page"],
                   "page_end": pages[pi]["page"], "ord": len(sections), "detection": det}
            sections.append(sec)
            stack.append(sec)
            current = sec
        current["page_end"] = max(current["page_end"], pages[pi]["page"])
        line_section[(pi, li)] = current["id"]

    # Front matter end page
    if len(sections) > 1:
        sections[0]["page_end"] = max(1, sections[1]["page_start"])
    return {"sections": sections, "line_section": line_section, "toc_pages": sorted(tocp), "body_size": body,
            "heading_source": "toc" if used_toc else "layout",
            "heading_lines": {h["pos"] for h in headings if h.get("consumes_line", True)}
            | {e for h in headings for e in h.get("extra", [])}}


def _headings_from_toc(toc: list, pages: list[dict], flat: list) -> list[dict]:
    page_index = {p["page"]: pi for pi, p in enumerate(pages)}
    by_page: dict[int, list[int]] = {}
    for idx, (pi, li, l) in enumerate(flat):
        by_page.setdefault(pi, []).append(idx)
    out, used = [], set()
    for lvl, title, pg in toc:
        pi = page_index.get(pg)
        if pi is None:
            continue
        m = NUM_HEADING.match(title)
        number, clean = (m.group(1), m.group(2).strip()) if m else ("", title.strip())
        target = None
        best = 0.0
        for idx in by_page.get(pi, []):
            if idx in used:
                continue
            lt = flat[idx][2]["text"]
            if flat[idx][2].get("toc_page"):
                continue
            mm = NUM_HEADING.match(lt)
            lt_clean = mm.group(2) if mm else lt
            r = SequenceMatcher(None, lt_clean.lower()[:80], clean.lower()[:80]).ratio()
            if r > best:
                best, target = r, idx
        consumes = best >= 0.6
        if not consumes:
            # heading not found as a line: attach to the first line of the page
            target = next((i for i in by_page.get(pi, []) if i not in used), None)
        if target is None:
            continue
        used.add(target)
        out.append({"pos": target, "number": number, "title": clean[:200], "level": int(lvl),
                    "detection": "toc", "consumes_line": consumes})
    out.sort(key=lambda h: h["pos"])
    # de-duplicate positions (keep first)
    seen, res = set(), []
    for h in out:
        if h["pos"] not in seen:
            res.append(h)
            seen.add(h["pos"])
    return res


def _headings_from_layout(flat: list, body: float) -> list[dict]:
    out = []
    n = len(flat)
    i = 0
    while i < n:
        pi, li, l = flat[i]
        t = l["text"]
        if l.get("in_table") or l.get("toc_page") or len(t) > 150:
            i += 1
            continue
        emph = l["bold"] or l["size"] >= body + 0.8
        caps = t.isupper() and len(t) > 4 and sum(ch.isalpha() for ch in t) > 3
        m = NUM_HEADING.match(t)
        mo = NUM_ONLY.match(t)
        if mo and i + 1 < n:
            # number on its own line followed by the title line (same page)
            npi, nli, nl = flat[i + 1]
            nt = nl["text"]
            if (npi == pi and (nl["bold"] or nl["size"] >= body + 0.8 or nt.isupper()) and len(nt) < 120
                    and nt[:1].isalpha() and not nt.endswith((",", ";")) and not DOT_LEADER.search(nt)):
                depth = mo.group(1).count(".") + 1
                if _plausible_number(mo.group(1)):
                    out.append({"pos": i, "number": mo.group(1), "title": nt.strip(), "level": depth,
                                "detection": "heading", "consumes_line": True, "extra": [i + 1]})
                    i += 2
                    continue
        if m and (emph or caps) and _plausible_number(m.group(1)) and not t.rstrip().endswith((",", ";")) \
                and len(m.group(2).split()) <= 18 and not DOT_LEADER.search(t):
            depth = m.group(1).count(".") + 1
            out.append({"pos": i, "number": m.group(1), "title": m.group(2).strip(), "level": depth,
                        "detection": "heading", "consumes_line": True})
        elif APPENDIX.match(t) and (emph or caps) and len(t) < 120:
            out.append({"pos": i, "number": "", "title": t.strip(), "level": 1, "detection": "heading",
                        "consumes_line": True})
        elif (emph and l["size"] >= body + 1.5 or (caps and l["bold"])) and 3 <= len(t) <= 90 \
                and len(t.split()) <= 12 and not t.endswith((".", ",", ";", ":")) and t[:1].isalpha():
            out.append({"pos": i, "number": "", "title": t.strip(), "level": 1 if l["size"] >= body + 3 else 2,
                        "detection": "heading", "consumes_line": True})
        i += 1
    return _merge_wrapped(out, flat)


def _merge_wrapped(heads: list[dict], flat: list) -> list[dict]:
    """Join heading titles that wrap onto following lines with identical styling."""
    taken = {h["pos"] for h in heads} | {e for h in heads for e in h.get("extra", [])}
    merged: list[dict] = []
    for h in heads:
        if any(h["pos"] in m.get("extra", []) for m in merged[-1:]):
            continue  # this line was absorbed as a continuation of the previous heading
        last = max([h["pos"], *h.get("extra", [])])
        ref = flat[last][2]
        j = last + 1
        while j < len(flat) and len(h.get("extra", [])) < 6:
            pj, _, lj = flat[j]
            if pj != flat[last][0] or lj.get("in_table"):
                break
            gap = lj["bbox"][1] - ref["bbox"][3]
            same_style = abs(lj["size"] - ref["size"]) < 0.4 and lj["bold"] == ref["bold"]
            if not same_style or gap > 0.8 * max(ref["bbox"][3] - ref["bbox"][1], 6) or NUM_HEADING.match(lj["text"])                     or NUM_ONLY.match(lj["text"]) or ref["text"].rstrip().endswith((".", ":")) or len(h["title"]) > 320:
                break
            h["title"] = f"{h['title']} {lj['text'].strip()}"
            h.setdefault("extra", []).append(j)
            ref, last = lj, j
            j += 1
        merged.append(h)
    absorbed = {e for h in merged for e in h.get("extra", [])}
    return [h for h in merged if h["pos"] not in absorbed]


def _plausible_number(num: str) -> bool:
    parts = [int(x) for x in num.split(".") if x]
    return bool(parts) and parts[0] <= 40 and all(p <= 60 for p in parts)
