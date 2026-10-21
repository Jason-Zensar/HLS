"""Local AI assistant endpoints: settings, protocol study, RAG chat, research agent and AI explanations of results.

Answers stream as Server-Sent Events (text/event-stream). Event types:
  status  - progress message            sources - numbered sources used as context (with why each was retrieved)
  step    - agent step (thought/tool)    token   - piece of the answer text
  done    - grounding report, model, timing   error - friendly error (sources are still shown)
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core import metadb
from app.llm import agent, client, glossary, grounding, prompts
from app.llm import settings as ai_settings
from app.llm.protocol_brief import brief_as_context, build_brief
from app.llm.retrieval import graph_facts, number_sources, render_sources, retrieve

router = APIRouter(prefix="/api/ai", tags=["local AI assistant"])


def _sse(events: Iterator[dict]) -> StreamingResponse:
    def gen():
        try:
            for e in events:
                yield "data: " + json.dumps(e, default=str) + "\n\n"
        except Exception as e:  # noqa: BLE001 - report instead of breaking the stream
            yield "data: " + json.dumps({"type": "error", "message": f"{type(e).__name__}: {e}"}) + "\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _answer(messages: list[dict], sources: list[dict], kind: str, label: str, extra_done: dict | None = None,
            on_done=None) -> Iterator[dict]:
    """Stream a model answer over the given sources, then report grounding."""
    cfg = ai_settings.get()
    yield {"type": "sources", "sources": sources}
    t0 = time.time()
    text = ""
    try:
        yield {"type": "status", "message": f"Writing the answer with {cfg['model']}..."}
        for piece in client.stream_chat(messages):
            text += piece
            yield {"type": "token", "text": piece}
    except client.LLMError as e:
        yield {"type": "error", "message": str(e), "hint": "Open Settings > Local AI to start Ollama or choose an installed model. The sources above are still valid."}
        return
    g = grounding.check(text, sources)
    done = {"type": "done", "model": cfg["model"], "elapsed_ms": round((time.time() - t0) * 1000), "grounding": g, **(extra_done or {})}
    metadb.audit(f"ai.{kind}", f"{label[:160]} ({cfg['model']}, {g['verdict']})", None, {"cited": g["cited_sources"], "sources": len(sources)})
    if on_done:
        on_done(text, done)
    yield done


def _messages(user_content: str, history: list[dict] | None = None) -> list[dict]:
    msgs = [{"role": "system", "content": prompts.SYSTEM}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
    msgs.append({"role": "user", "content": user_content + CITE_RULE})
    return msgs


# question topic (preferred section categories from retrieval) -> sections of the protocol brief
SECTION_TO_BRIEF = {
    "dosing": ("What participants receive",), "treatment_arms": ("What participants receive",), "study_design": ("What participants receive",),
    "inclusion_criteria": ("Who can take part (inclusion criteria)",), "eligibility": ("Who can take part (inclusion criteria)", "Who cannot take part (exclusion criteria)"),
    "exclusion_criteria": ("Who cannot take part (exclusion criteria)",), "concomitant_medications": ("Who cannot take part (exclusion criteria)",),
    "primary_endpoints": ("What the study measures (endpoints)",), "secondary_endpoints": ("What the study measures (endpoints)",),
    "endpoints": ("What the study measures (endpoints)",), "objectives": ("What the study measures (endpoints)",),
    "adverse_events": ("Safety: side effects watched and safety rules",), "safety_monitoring": ("Safety: side effects watched and safety rules",),
    "biomarkers": ("Tests and biomarkers",), "schedule_of_assessments": ("Tests and biomarkers", "Follow-up and analysis"),
    "follow_up": ("Follow-up and analysis",), "statistics": ("Follow-up and analysis",),
}

CITE_RULE = ("\n\nIMPORTANT: write the source tag right after every fact, exactly like this example: "
             "\"- Participants must be at least 18 years old [S12].\" Use only tags that appear in the sources above.")


# ------------------------------------------------------------------ settings / status
@router.get("/status", summary="Is the local model server reachable, and which models are installed?")
def status():
    return client.status()


class SettingsBody(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = Field(None, pattern="^(ollama|openai)$")
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=1.5)
    context_tokens: Optional[int] = Field(None, ge=2048, le=131072)


@router.get("/settings")
def get_settings_():
    return ai_settings.public(ai_settings.get())


@router.put("/settings")
def put_settings(body: SettingsBody):
    changes = body.model_dump(exclude_none=True)
    if changes.get("api_key") == "****":
        changes.pop("api_key")
    cfg = ai_settings.update(changes)
    metadb.audit("ai.settings", f"AI settings changed: {', '.join(k for k in changes if k != 'api_key')}")
    return ai_settings.public(cfg)


@router.post("/test", summary="Send a tiny prompt to the configured model")
def test():
    try:
        return {"ok": True, **client.test()}
    except client.LLMError as e:
        raise HTTPException(503, str(e))


class PullBody(BaseModel):
    model: str = Field(..., min_length=2, max_length=120)


@router.post("/pull", summary="Download a model through Ollama (streams progress)")
def pull(body: PullBody):
    def events():
        for p in client.pull(body.model):
            yield {"type": "progress", **{k: p.get(k) for k in ("status", "completed", "total", "error")}}
        yield {"type": "done"}
    return _sse(events())


# ------------------------------------------------------------------ protocol study
@router.get("/protocol/{doc_id}/brief", summary="Plain-language structure of one protocol (no AI needed)")
def protocol_brief(doc_id: str):
    try:
        return build_brief(doc_id)
    except KeyError:
        raise HTTPException(404, "Document not found")


class ExplainProtocolBody(BaseModel):
    doc_id: str
    refresh: bool = False


@router.post("/explain/protocol", summary="Elaborate plain-language explanation of one protocol (streamed, cached per model)")
def explain_protocol(body: ExplainProtocolBody):
    try:
        b = build_brief(body.doc_id)
    except KeyError:
        raise HTTPException(404, "Document not found")
    cfg = ai_settings.get()
    cached = None if body.refresh else metadb.q1("SELECT * FROM ai_explanations WHERE doc_id=? AND model=?", (body.doc_id, cfg["model"]))

    def events():
        if cached:
            yield {"type": "sources", "sources": json.loads(cached["sources"])}
            yield {"type": "token", "text": cached["text"]}
            yield {**json.loads(cached["meta"]), "type": "done", "cached": True, "created_at": cached["created_at"]}
            return
        yield {"type": "status", "message": "Collecting the protocol's key facts and sections..."}
        context, sources = brief_as_context(b)
        user = prompts.EXPLAIN_PROTOCOL.format(context=context, glossary=glossary.as_reference(b["glossary"][:25]))

        def save(text: str, done: dict):
            metadb.execute("INSERT OR REPLACE INTO ai_explanations(doc_id, model, created_at, text, sources, meta) VALUES (?,?,?,?,?,?)",
                           (body.doc_id, cfg["model"], time.time(), text, json.dumps(sources), json.dumps(done)))
        yield from _answer(_messages(user), sources, "explain_protocol", b["doc"]["filename"], on_done=save)
    return _sse(events())


# ------------------------------------------------------------------ chat (RAG) and agent
class ChatBody(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    history: list[dict[str, Any]] = []
    doc_id: Optional[str] = None
    mode: str = Field("rag", pattern="^(rag|agent)$")


@router.post("/chat", summary="Ask a question about one protocol or all protocols (RAG or agent), streamed with sources")
def chat(body: ChatBody):
    doc = metadb.q1("SELECT id, filename, title FROM documents WHERE id=?", (body.doc_id,)) if body.doc_id else None
    if body.doc_id and not doc:
        raise HTTPException(404, "Document not found")
    scope_note = (f"Scope: one protocol only - {doc['filename']} ({doc['title'] or ''})." if doc
                  else "Scope: all protocols in the collection.")

    def events():
        if body.mode == "agent":
            yield {"type": "status", "message": "Research agent is planning..."}
            pool: list[dict] = []
            for ev in agent.run(body.question, doc["id"] if doc else None, body.history):
                if ev["type"] == "pool":
                    pool = ev["sources"]
                else:
                    yield ev
            sources = pool[:24]
            user = prompts.AGENT_FINAL.format(scope_note=scope_note, sources=render_sources(sources, 600), question=body.question)
        else:
            yield {"type": "status", "message": "Searching the protocol text" + (" and the knowledge graph" if not doc else "") + "..."}
            r = retrieve(body.question, doc_id=doc["id"] if doc else None, k=7 if doc else 6)
            groups = [r["sources"]]
            if doc:  # one protocol: its structured facts for the topic of the question come first, then text passages
                _, bsrc = brief_as_context(build_brief(doc["id"]))
                wanted = {t for c in r["preferred_sections"] for t in SECTION_TO_BRIEF.get(c, ())}
                facts = [s for s in bsrc if s["kind"] == "fact" and s["section"] in wanted][:8]
                if not facts and len(r["sources"]) < 3:
                    facts = [s for s in bsrc if s["kind"] != "reference"][:8]
                groups.insert(0, facts)
            if not doc:
                g = graph_facts(body.question, limit=6)
                groups.insert(0, g["sources"])
            sources = number_sources(groups)[:12]
            yield {"type": "retrieval", "terms": r["terms"], "expanded_terms": r["expanded_terms"], "concepts": [c["name"] for c in r["concepts"]],
                   "preferred_sections": r["preferred_sections"]}
            user = prompts.CHAT.format(scope_note=scope_note, sources=render_sources(sources), question=body.question)
        if not sources:
            yield {"type": "sources", "sources": []}
            yield {"type": "error", "message": "No relevant passages were found for this question.",
                   "hint": "Try other words (drug, disease or test names), or pick a protocol to search inside it."}
            return
        yield from _answer(_messages(user, body.history), sources, "chat", body.question, {"mode": body.mode, "scope": doc["filename"] if doc else "all"})
    return _sse(events())


# ------------------------------------------------------------------ AI explanations of other results
class ExplainQueryBody(BaseModel):
    query_id: str


@router.post("/explain/query", summary="Plain-language explanation of a stored graph query result")
def explain_query(body: ExplainQueryBody):
    row = metadb.q1("SELECT question, response FROM queries WHERE id=?", (body.query_id,))
    if not row or not row["response"]:
        raise HTTPException(404, "Query not found")
    resp = json.loads(row["response"])

    def events():
        src, seen = [], set()
        for p in resp.get("evidence_passages", []):
            key = (p["subject"], p["relationship"], p["object"], p["doc_id"])
            if key in seen:
                continue
            seen.add(key)
            rel = p["relationship"].lower().replace("_", " ")
            src.append({"kind": "fact", "doc_id": p["doc_id"], "filename": p.get("filename"), "title": p.get("document_title"), "nct_id": p.get("nct_id"),
                        "page_start": p["page_start"], "page_end": p["page_end"], "section": p.get("section"), "chunk_id": p["chunk_id"],
                        "text": f"Fact: {p['subject']} - {rel} - {p['object']}. Quote: \"{(p['quote'] or '')[:450]}\"", "why": f"graph result ({rel})"})
            if len(src) >= 14:
                break
        sources = number_sources([src])
        if not sources:
            yield {"type": "sources", "sources": []}
            yield {"type": "error", "message": "This search returned no evidence passages to explain."}
            return
        user = prompts.EXPLAIN_QUERY.format(question=row["question"] or "", summary=(resp.get("answer_summary") or {}).get("text", "")[:1500],
                                            sources=render_sources(sources, 600))
        yield from _answer(_messages(user), sources, "explain_query", row["question"] or body.query_id)
    return _sse(events())


class ExplainEvidenceBody(BaseModel):
    q: str = Field(..., min_length=2)
    doc_id: str = ""
    section_category: str = ""


@router.post("/explain/evidence", summary="Plain-language summary of text-search results")
def explain_evidence(body: ExplainEvidenceBody):
    def events():
        r = retrieve(body.q, doc_id=body.doc_id or None, k=8)
        src = [s for s in r["sources"] if not body.section_category or s["section_category"] == body.section_category] or r["sources"]
        sources = number_sources([src])
        if not sources:
            yield {"type": "sources", "sources": []}
            yield {"type": "error", "message": "No passages matched these words."}
            return
        yield from _answer(_messages(prompts.EXPLAIN_EVIDENCE.format(query=body.q, sources=render_sources(sources))), sources, "explain_evidence", body.q)
    return _sse(events())


class ExplainCompareBody(BaseModel):
    protocol_ids: list[str] = Field(..., min_length=2, max_length=4)


@router.post("/explain/compare", summary="Plain-language explanation of a protocol comparison")
def explain_compare(body: ExplainCompareBody):
    from app.query.compare import compare_protocols

    def events():
        yield {"type": "status", "message": "Comparing the protocols field by field..."}
        res = compare_protocols([p if p.startswith("protocol:") else f"protocol:{p}" for p in body.protocol_ids])
        names = {p["id"]: (p.get("document") or {}).get("filename") or p["title"] for p in res["protocols"]}
        src = []
        for f in res["fields"]:
            for pid in names:
                vals = f["values"].get(pid, [])
                if not vals:
                    src.append({"kind": "fact", "doc_id": pid.split(":", 1)[1], "filename": names[pid], "title": names[pid], "nct_id": None,
                                "page_start": None, "page_end": None, "section": f["label"], "chunk_id": None,
                                "text": f"{names[pid]} - {f['label']}: not found in the document", "why": f"comparison field '{f['label']}' ({f['status']})"})
                    continue
                cap = 4 if f["field"] in ("inclusion", "exclusion") else 3
                joined = "; ".join(v["value"][:160] for v in vals[:cap])
                ev = vals[0]["evidence"]
                src.append({"kind": "fact", "doc_id": ev["doc_id"], "filename": names[pid], "title": names[pid], "nct_id": None,
                            "page_start": ev["page"], "page_end": ev["page"], "section": f["label"], "chunk_id": None,
                            "text": f"{names[pid]} - {f['label']} [{f['status']}]: {joined}", "why": f"comparison field '{f['label']}' ({f['status']})"})
        sources = number_sources([src])[:40]
        user = prompts.EXPLAIN_COMPARE.format(names=", ".join(names.values()), sources=render_sources(sources, 400))
        yield from _answer(_messages(user), sources, "explain_compare", " vs ".join(names.values()))
    return _sse(events())
