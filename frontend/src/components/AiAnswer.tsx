// Displays a streamed local-AI answer with full explainability: cited sources, automatically matched sources,
// a grounding check, the agent's steps and the retrieval details.
import clsx from "clsx";
import { AlertTriangle, Bot, CheckCircle2, ChevronDown, FileText, Info, Loader2, RefreshCw, Settings, Sparkles, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAiRun, useAiStatus, type AiRun, type AiSource } from "../lib/ai";
import type { SourceRef } from "./SourceViewer";
import { Md } from "./Md";

export function AiToggle({ on, onChange, label = "Explain with local AI" }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  const st = useAiStatus();
  const ready = st.data?.ready;
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-2 rounded-md border border-ink-200 bg-white px-2.5 py-1.5 text-[12.5px] text-ink-700"
      title={ready ? `Model: ${st.data?.settings.model}` : st.data?.error || "Local AI not configured"}>
      <span className={clsx("relative inline-flex h-4 w-7 items-center rounded-full transition", on ? "bg-violet-600" : "bg-ink-300")}>
        <span className={clsx("absolute h-3 w-3 rounded-full bg-white shadow transition", on ? "left-3.5" : "left-0.5")} />
      </span>
      <input type="checkbox" className="hidden" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <Sparkles className="h-3.5 w-3.5 text-violet-600" />{label}
      {on && st.data && !ready && <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />}
    </label>
  );
}

export function AiNotReady() {
  const st = useAiStatus();
  if (!st.data || st.data.ready) return null;
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12.5px] text-amber-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>{!st.data.enabled ? "Local AI is switched off." : st.data.error}{" "}
        <Link to="/settings" className="font-medium underline">Open AI settings</Link></div>
    </div>
  );
}

/** Self-running panel: starts when `runKey` changes. */
export function AiAnswer({ endpoint, body, runKey, title = "AI explanation", onSource, regenerateBody }: {
  endpoint: string; body: unknown; runKey: string; title?: string; onSource?: (s: SourceRef) => void; regenerateBody?: unknown;
}) {
  const { run, start, stop } = useAiRun(endpoint);
  useEffect(() => { if (runKey) start(body); /* eslint-disable-next-line */ }, [runKey]);
  return <AiResult run={run} title={title} onSource={onSource} onStop={stop} onRegenerate={() => start(regenerateBody ?? body)} />;
}

export function AiResult({ run, title, onSource, onStop, onRegenerate, compact }: {
  run: AiRun; title?: string; onSource?: (s: SourceRef) => void; onStop?: () => void; onRegenerate?: () => void; compact?: boolean;
}) {
  const [active, setActive] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(!compact);
  const text = run.done?.grounding?.annotated_text || run.text;
  const byId = useMemo(() => new Map(run.sources.map((s) => [s.id, s])), [run.sources]);
  const g = run.done?.grounding;
  const cited = new Set(g?.cited_sources || []);
  const matched = new Set(g?.matched_sources || []);
  const openSource = (s: AiSource) => {
    if (onSource && s.page_start && s.kind !== "reference") onSource({ docId: s.doc_id, page: s.page_start, chunkId: s.chunk_id || undefined, quote: s.kind === "fact" ? s.text : undefined, title: s.title || s.filename });
  };
  const onCite = (id: string) => {
    setActive(id);
    setShowSources(true);
    setTimeout(() => document.getElementById(`src-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
  };
  return (
    <section className="rounded-lg border border-violet-200 bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <header className="flex flex-wrap items-center gap-2 border-b border-violet-100 bg-violet-50/60 px-4 py-2">
        <Bot className="h-4 w-4 text-violet-700" />
        <span className="text-[13px] font-semibold text-ink-800">{title}</span>
        {run.done && <span className="text-[11.5px] text-ink-500">· {run.done.model} · {(run.done.elapsed_ms / 1000).toFixed(1)} s{run.done.cached ? " · saved answer" : ""}</span>}
        <div className="ml-auto flex items-center gap-1.5">
          {run.running && onStop && <button onClick={onStop} className="inline-flex items-center gap-1 rounded border border-ink-200 bg-white px-2 py-0.5 text-[12px] text-ink-700 hover:bg-ink-50"><Square className="h-3 w-3" />Stop</button>}
          {!run.running && onRegenerate && (run.done || run.error) && <button onClick={onRegenerate} className="inline-flex items-center gap-1 rounded border border-ink-200 bg-white px-2 py-0.5 text-[12px] text-ink-700 hover:bg-ink-50"><RefreshCw className="h-3 w-3" />Regenerate</button>}
        </div>
      </header>
      <div className="space-y-3 px-4 py-3">
        {run.status && <div className="flex items-center gap-2 text-[12.5px] text-ink-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />{run.status}</div>}
        {run.steps.length > 0 && (
          <details className="rounded-md border border-ink-200 bg-ink-50/60 px-3 py-2 text-[12.5px]" open={run.running}>
            <summary className="cursor-pointer font-medium text-ink-700">How the research agent worked ({run.steps.length} steps)</summary>
            <ol className="mt-2 space-y-1.5">{run.steps.map((s, i) => (
              <li key={i} className="rounded bg-white px-2 py-1.5 ring-1 ring-ink-100">
                <div><b className="text-violet-700">{s.action === "final" ? "Answer" : s.action.replace(/_/g, " ")}</b>
                  {s.action !== "final" && <span className="text-ink-500"> {Object.values(s.args || {}).map((v) => (Array.isArray(v) ? v.join(", ") : String(v))).join(" · ")}</span>}</div>
                {s.thought && <div className="text-ink-500">Reasoning: {s.thought}</div>}
                {s.result && <div className="text-ink-600">Result: {s.result}</div>}
              </li>))}</ol>
          </details>
        )}
        {run.error && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12.5px] text-amber-800">
            <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" />{run.error.message}</div>
            {run.error.hint && <div className="mt-1">{run.error.hint} <Link to="/settings" className="inline-flex items-center gap-0.5 underline"><Settings className="h-3 w-3" />AI settings</Link></div>}
          </div>
        )}
        {text && <Md text={text} onCite={onCite} active={active} />}
        {run.running && text && <span className="inline-block h-4 w-1.5 animate-pulse bg-violet-500 align-middle" />}

        {g && (
          <div className={clsx("rounded-md border px-3 py-2 text-[12.5px]", g.verdict === "well grounded" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : g.verdict === "partly grounded" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-rose-200 bg-rose-50 text-rose-900")}>
            <div className="flex items-center gap-1.5 font-semibold">
              {g.verdict === "well grounded" ? <CheckCircle2 className="h-4 w-4" /> : <Info className="h-4 w-4" />}
              Explainability check: {g.verdict}
            </div>
            <ul className="mt-1 space-y-0.5">
              <li>{g.statements_cited} of {g.statements} statements cite a source{g.statements_matched ? `; ${g.statements_matched} more were matched automatically to a source (dashed ~S tags)` : ""}.</li>
              <li>{g.numbers_checked} numbers checked against the sources{g.numbers_unverified.length ? <>; <b>not found in the sources: {g.numbers_unverified.join(", ")}</b> - verify these</> : " - all found"}.</li>
              {g.invalid_citations.length > 0 && <li><b>Citations to sources that do not exist: {g.invalid_citations.join(", ")}</b></li>}
              {run.retrieval && <li>Search used: {[...(run.retrieval.terms || []), ...(run.retrieval.expanded_terms || [])].slice(0, 12).join(", ")}{run.retrieval.preferred_sections?.length ? `; preferred sections: ${run.retrieval.preferred_sections.slice(0, 4).join(", ")}` : ""}</li>}
            </ul>
          </div>
        )}

        {run.sources.length > 0 && (
          <div>
            <button onClick={() => setShowSources((v) => !v)} className="flex items-center gap-1 text-[12px] font-semibold uppercase tracking-wide text-ink-500 hover:text-ink-800">
              <ChevronDown className={clsx("h-3.5 w-3.5 transition", !showSources && "-rotate-90")} />Sources given to the AI ({run.sources.length})
              {g && <span className="font-normal normal-case text-ink-400"> · {cited.size} cited, {[...matched].filter((x) => !cited.has(x)).length} matched</span>}
            </button>
            {showSources && (
              <ol className="mt-2 max-h-[420px] space-y-1.5 overflow-auto pr-1">{run.sources.map((s) => (
                <li key={s.id} id={`src-${s.id}`} className={clsx("rounded-md border px-2.5 py-1.5 text-[12px]", active === s.id ? "border-blue-400 bg-blue-50" : cited.has(s.id) ? "border-blue-200" : matched.has(s.id) ? "border-dashed border-ink-300" : "border-ink-100")}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <b className="text-ink-800">{s.id}</b>
                    {cited.has(s.id) && <span className="rounded bg-blue-100 px-1 text-[10.5px] font-semibold text-blue-800">cited</span>}
                    {!cited.has(s.id) && matched.has(s.id) && <span className="rounded border border-dashed border-ink-300 px-1 text-[10.5px] text-ink-500">matched</span>}
                    {s.kind === "reference" && <span className="rounded bg-ink-100 px-1 text-[10.5px] text-ink-600">general reference</span>}
                    <span className="text-ink-600">{s.filename}{s.page_start ? ` · p.${s.page_start}` : ""}{s.section ? ` · ${s.section}` : ""}</span>
                    {s.page_start && s.kind !== "reference" && onSource && <button onClick={() => openSource(s)} className="ml-auto inline-flex items-center gap-1 rounded border border-ink-200 px-1.5 py-0.5 text-ink-700 hover:bg-ink-50"><FileText className="h-3 w-3" />View page</button>}
                  </div>
                  {s.why && <div className="text-[11px] text-ink-400">Why chosen: {s.why}</div>}
                  <p className="mt-0.5 line-clamp-3 text-ink-600" title={s.text}>{s.text}</p>
                </li>))}</ol>
            )}
          </div>
        )}
        {(run.done || run.text) && <p className="text-[11px] leading-snug text-ink-400">Written by a local AI model using only the protocol text listed above. Check important details in the original pages. This is an explanation of study documents, not medical advice.</p>}
      </div>
    </section>
  );
}
