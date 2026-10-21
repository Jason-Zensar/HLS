"""Local research agent: the model plans tool calls over the protocol corpus, then writes a cited answer.

Each tool returns sources (passages / validated facts) that join one numbered pool, so the final answer can cite them and
every step (thought, tool, arguments, what was found) is reported to the user for transparency.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

from app.core import metadb
from app.llm import client, prompts
from app.llm.protocol_brief import brief_as_context, build_brief
from app.llm.retrieval import graph_facts, retrieve

MAX_STEPS = 4
TOOLS = ("find_protocols", "protocol_overview", "search_text", "graph_search", "compare")


def resolve_protocol(ref: str | None) -> dict | None:
    if not ref:
        return None
    ref = str(ref).strip().strip('"')
    if re.fullmatch(r"d[0-9a-f]{12}", ref):
        return metadb.q1("SELECT id, filename, title, nct_id FROM documents WHERE id=?", (ref,))
    if ref.lower().startswith("protocol:"):
        return metadb.q1("SELECT id, filename, title, nct_id FROM documents WHERE id=?", (ref.split(":", 1)[1],))
    row = metadb.q1("SELECT id, filename, title, nct_id FROM documents WHERE nct_id = ? OR sponsor_protocol_code = ?", (ref.upper(), ref))
    if row:
        return row
    like = f"%{ref}%"
    row = metadb.q1("""SELECT id, filename, title, nct_id FROM documents WHERE filename LIKE ? OR title LIKE ?
                       ORDER BY (filename LIKE ?) DESC, length(filename) LIMIT 1""", (like, like, like))
    if row or len(ref) < 4:
        return row
    # trial acronyms are often only inside the text (e.g. a file whose name differs): pick the document that mentions it most
    try:
        hit = metadb.q1("""SELECT c.doc_id, count(*) n FROM chunks_fts f JOIN chunks c ON c.id = f.chunk_id
                           WHERE chunks_fts MATCH ? AND c.page_start <= 3 GROUP BY c.doc_id ORDER BY n DESC LIMIT 1""",
                        ('"' + ref.replace('"', "") + '"',))  # title pages only: a name mentioned in background text is not the study
    except Exception:
        hit = None
    return metadb.q1("SELECT id, filename, title, nct_id FROM documents WHERE id=?", (hit["doc_id"],)) if hit else None


def _find_protocols(keywords: str) -> list[dict]:
    like = f"%{keywords}%"
    rows = metadb.q("""SELECT id, filename, title, nct_id, phase FROM documents WHERE filename LIKE ? OR title LIKE ? OR nct_id LIKE ? OR sponsor LIKE ?
                       LIMIT 10""", (like, like, like, like))
    if len(rows) < 5:  # also look for protocols whose text mentions the keywords most often
        r = retrieve(keywords, k=12, per_doc=1)
        have = {x["id"] for x in rows}
        for s in r["sources"]:
            if s["doc_id"] not in have:
                have.add(s["doc_id"])
                rows.append({"id": s["doc_id"], "filename": s["filename"], "title": s["title"], "nct_id": s["nct_id"], "phase": None})
    return rows[:10]


def _run_tool(action: str, args: dict, scope_doc: str | None) -> tuple[str, list[dict]]:
    """Execute one tool. Returns (short summary for the trace, new sources)."""
    if action == "find_protocols":
        rows = _find_protocols(str(args.get("keywords") or ""))
        text = "; ".join(f"{r['filename']} (id {r['id']}{', ' + r['nct_id'] if r.get('nct_id') else ''})" for r in rows) or "no protocols found"
        return f"Found {len(rows)} protocol(s): {text}", []
    if action == "protocol_overview":
        d = resolve_protocol(args.get("protocol")) or (resolve_protocol(scope_doc) if scope_doc else None)
        if not d:
            return f"Protocol '{args.get('protocol')}' not found", []
        b = build_brief(d["id"])
        _, src = brief_as_context(b)
        return f"Overview of {d['filename']}: {b['one_liner']}", src[:12]
    if action == "search_text":
        d = resolve_protocol(args.get("protocol")) if args.get("protocol") else None
        doc_id = d["id"] if d else scope_doc
        r = retrieve(str(args.get("query") or ""), doc_id=doc_id, k=6)
        return f"{len(r['sources'])} passage(s) found" + (f" in {d['filename']}" if d else ""), r["sources"]
    if action == "graph_search":
        r = graph_facts(str(args.get("question") or ""), limit=8)
        return f"{len(r['sources'])} validated fact(s); matched: {', '.join(r.get('matched') or []) or 'none'}", r["sources"]
    if action == "compare":
        from app.query.compare import compare_protocols
        refs = [str(p) for p in (args.get("protocols") or [])][:4]
        found = {r: resolve_protocol(r) for r in refs}
        docs = list({d["id"]: d for d in found.values() if d}.values())
        if len(docs) < 2:
            missing = [r for r, d in found.items() if not d]
            return (f"Could not compare: protocol(s) not found: {', '.join(missing) or 'fewer than two given'}. "
                    "Try find_protocols or protocol_overview instead."), []
        res = compare_protocols([f"protocol:{d['id']}" for d in docs])
        src = []
        names = {p["id"]: (p.get("document") or {}).get("filename") or p["title"] for p in res["protocols"]}
        key_fields = ("phase", "design", "subtype", "setting", "drugs", "arms", "dosing", "inclusion", "exclusion", "primary_endpoints", "safety")
        for f in [x for x in res["fields"] if x["field"] in key_fields]:
            for pid, vals in f["values"].items():
                if not vals:
                    src.append({"kind": "fact", "doc_id": pid.split(":", 1)[1], "filename": names.get(pid), "title": names.get(pid), "nct_id": None,
                                "page_start": None, "page_end": None, "section": f["label"], "chunk_id": None,
                                "text": f"{names.get(pid)} - {f['label']}: not found in the document", "why": f"comparison field '{f['label']}'"})
                    continue
                ev = vals[0]["evidence"]
                joined = "; ".join(v["value"][:150] for v in vals[:4 if f["field"] in ("inclusion", "exclusion") else 3])
                src.append({"kind": "fact", "doc_id": ev["doc_id"], "filename": names.get(pid), "title": names.get(pid), "nct_id": None,
                            "page_start": ev["page"], "page_end": ev["page"], "section": f["label"], "chunk_id": None,
                            "text": f"{names.get(pid)} - {f['label']} ({f['status']}): {joined}", "why": f"comparison field '{f['label']}'"})
        return f"Compared {len(docs)} protocols on {len(key_fields)} key fields", src
    return f"Unknown tool '{action}'", []


def run(question: str, scope_doc: str | None, history: list[dict]) -> Iterator[dict[str, Any]]:
    """Yields {'type':'step', ...} events, then {'type':'pool', 'sources': [...]} with the numbered source pool."""
    pool: list[dict] = []
    observations: list[str] = []
    scope_note = ""
    if scope_doc:
        d = resolve_protocol(scope_doc)
        scope_note = f"The user is studying one protocol: {d['filename']} (id {d['id']}). Prefer tools on this protocol." if d else ""

    def add_sources(src: list[dict]) -> list[str]:
        ids = []
        seen = {(s.get("chunk_id"), s["text"][:80]) for s in pool}
        for s in src:
            key = (s.get("chunk_id"), s["text"][:80])
            if key in seen:
                continue
            seen.add(key)
            s = {**s, "id": f"S{len(pool) + 1}"}
            pool.append(s)
            ids.append(s["id"])
        return ids

    used = 0
    tried: set[str] = set()
    tried_overview: set[str] = set()
    for step in range(1, MAX_STEPS + 2):
        obs_text = "\n".join(observations) or "(nothing yet)"
        prompt = prompts.AGENT.format(scope_note=scope_note, question=question, observations=obs_text, max_steps=MAX_STEPS, used=used)
        try:
            raw = client.chat([{"role": "system", "content": "You are a careful planner. Output JSON only."}, {"role": "user", "content": prompt}],
                              json_mode=True, temperature=0.1, max_tokens=300)
            plan = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception as e:  # noqa: BLE001 - small models occasionally break format; fall back to plain retrieval
            plan = {"thought": f"planner output unusable ({type(e).__name__}); using text search", "action": "search_text" if not pool else "final",
                    "args": {"query": question}}
        action = str(plan.get("action") or "final").strip()
        args = plan.get("args") if isinstance(plan.get("args"), dict) else {}
        if action == "final" or used >= MAX_STEPS:
            if not pool:  # never answer without evidence
                action, args = ("protocol_overview", {"protocol": scope_doc}) if scope_doc else ("search_text", {"query": question})
            else:
                yield {"type": "step", "step": step, "thought": plan.get("thought", ""), "action": "final", "args": {}, "result": "Enough information gathered."}
                break
        if action not in TOOLS:
            action, args = "search_text", {"query": question}
        if action == "search_text" and not args.get("query"):
            args["query"] = question
        signature = action + json.dumps(args, sort_keys=True)
        if signature in tried:  # small models sometimes repeat a step; never run the same call twice
            if pool:
                yield {"type": "step", "step": step, "thought": "Repeated step skipped; answering with what was found.", "action": "final", "args": {}, "result": ""}
                break
            refs = args.get("protocols") or ([args["protocol"]] if args.get("protocol") else [])
            action, args = ("protocol_overview", {"protocol": refs[0]}) if refs and f"protocol_overview{refs[0]}" not in tried_overview else ("search_text", {"query": question})
            signature = action + json.dumps(args, sort_keys=True)
        tried.add(signature)
        if action == "protocol_overview":
            tried_overview.add(f"protocol_overview{args.get('protocol')}")
        try:
            summary, src = _run_tool(action, args, scope_doc)
        except Exception as e:  # noqa: BLE001
            summary, src = f"Tool failed: {type(e).__name__}", []
        ids = add_sources(src)
        used += 1
        observations.append(f"Step {used}: {action}({json.dumps(args)[:200]}) -> {summary}" +
                            ("".join(f"\n  [{s['id']}] {s.get('filename')}, p.{s.get('page_start')}: {s['text'][:260]}" for s in pool if s["id"] in ids)))
        yield {"type": "step", "step": step, "thought": plan.get("thought", ""), "action": action, "args": args, "result": summary, "sources": ids}
    yield {"type": "pool", "sources": pool}
