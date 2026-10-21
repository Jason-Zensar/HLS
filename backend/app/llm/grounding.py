"""Explainability checks on a generated answer.

For every statement (sentence) the check records whether the model cited a source. Statements without a citation are
matched to the source with the highest word overlap and marked [~S#] (shown as "matched automatically"). It also flags
citations to sources that do not exist and numbers in the answer that do not occur in the sources.
"""
from __future__ import annotations

import re

CITE = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
CITE_ONLY = re.compile(r"(\s*\[S\d+(?:\s*[,;]\s*S\d+)*\]\s*)+")
NUM = re.compile(r"(?<![A-Za-z0-9\-])(\d+(?:[.,]\d+)?)\s?(mg/m2|mg/m²|mg/kg|mg|mcg|µg|g/dl|g/dL|%|days?|weeks?|months?|years?|cycles?|hours?)?(?![A-Za-z0-9])")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_STOPW = set("""a an and are as at be been by for from has have in into is it its of on or that the their this to was were will with which
who can may must not any all each they them than then there these those also other such per including include includes study participants
patients protocol trial""".split())


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-/]+", t.lower()) if w not in _STOPW and len(w) > 2}


def _ids(text: str) -> list[str]:
    return [sid for m in CITE.finditer(text) for sid in re.findall(r"S\d+", m.group(1))]


def check(answer: str, sources: list[dict], threshold: float = 0.3) -> dict:
    ids = {s["id"] for s in sources}
    src_words = [(s["id"], _words(s["text"])) for s in sources]
    statements: list[dict] = []
    para = 0
    lines = answer.split("\n")
    for li, raw in enumerate(lines):
        body = raw.strip()
        if not body:
            para += 1
            continue
        if body.startswith("#"):
            para += 1
            continue
        if CITE_ONLY.fullmatch(body):  # citations on their own line apply to the paragraph just above
            target = max((s["para"] for s in statements), default=None)
            for s in statements:
                if s["para"] == target:
                    s["cited"] = True
            continue
        text = CITE.sub("", body).strip().lstrip("-*•0123456789.) ").strip()
        line_cited = bool(CITE.search(body))
        for sent in SENT.split(text):
            if len(sent.strip()) >= 25:
                statements.append({"text": sent.strip(), "line": li, "para": para, "cited": line_cited, "match": None})

    for s in statements:
        if s["cited"]:
            continue
        w = _words(s["text"])
        if len(w) < 3:
            continue
        best, best_score = None, 0.0
        for sid, sw in src_words:
            score = len(w & sw) / len(w)
            if score > best_score:
                best, best_score = sid, score
        if best and best_score >= threshold:
            s["match"] = best

    # annotate: add [~S#] at the end of lines whose statements were matched automatically
    per_line: dict[int, list[str]] = {}
    for s in statements:
        if s["match"]:
            per_line.setdefault(s["line"], [])
            if s["match"] not in per_line[s["line"]]:
                per_line[s["line"]].append(s["match"])
    annotated = "\n".join(raw.rstrip() + "".join(f" [~{sid}]" for sid in per_line[i][:2]) if i in per_line else raw for i, raw in enumerate(lines))

    cited = list(dict.fromkeys(_ids(answer)))
    invalid = [c for c in cited if c not in ids]
    valid = [c for c in cited if c in ids]
    by_id = {s["id"]: s for s in sources}
    pool = " ".join(by_id[c]["text"] for c in valid) + " " + " ".join(by_id[s["match"]]["text"] for s in statements if s["match"])
    names = " ".join(f"{s.get('filename') or ''} {s.get('title') or ''} {s.get('nct_id') or ''}" for s in sources)  # trial names / ids
    norm_src = ((pool if pool.strip() else " ".join(s["text"] for s in sources)) + " " + names).replace(",", "")
    checked, unverified = 0, []
    for m in NUM.finditer(CITE.sub(" ", answer)):
        num, unit = m.group(1), m.group(2)
        if not unit and len(num.replace(".", "").replace(",", "")) < 2:
            continue  # bare single digits (list numbers, "phase 2") are not checked
        checked += 1
        if num.replace(",", "") not in norm_src:
            unverified.append((num + (" " + unit if unit else "")).strip())
    n = len(statements)
    n_cited = sum(1 for s in statements if s["cited"])
    n_matched = sum(1 for s in statements if s["match"])
    support = round((n_cited + n_matched) / n, 2) if n else 0.0
    verdict = "well grounded" if support >= 0.7 and not invalid and not unverified else "partly grounded" if support >= 0.4 else "weakly grounded"
    return {"cited_sources": valid, "matched_sources": sorted({s["match"] for s in statements if s["match"]}, key=lambda x: int(x[1:])),
            "invalid_citations": invalid, "statements": n, "statements_cited": n_cited, "statements_matched": n_matched,
            "citation_coverage": round(n_cited / n, 2) if n else 0.0, "support_ratio": support, "numbers_checked": checked,
            "numbers_unverified": sorted(set(unverified))[:12], "verdict": verdict, "annotated_text": annotated}
