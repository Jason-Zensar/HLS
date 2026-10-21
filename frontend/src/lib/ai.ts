// Local AI assistant: streaming client, status hook and per-area on/off toggles.
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface AiSource {
  id: string; kind: "passage" | "fact" | "reference"; doc_id: string; filename?: string; title?: string; nct_id?: string;
  page_start?: number | null; page_end?: number | null; section?: string | null; chunk_id?: string | null; text: string; why?: string; score?: number;
}
export interface Grounding {
  cited_sources: string[]; matched_sources: string[]; invalid_citations: string[]; statements: number; statements_cited: number; statements_matched: number;
  citation_coverage: number; support_ratio: number; numbers_checked: number; numbers_unverified: string[]; verdict: string; annotated_text: string;
}
export interface AgentStep { step: number; thought: string; action: string; args: Record<string, any>; result: string; sources?: string[] }
export interface AiStatus {
  settings: { enabled: boolean; provider: string; base_url: string; model: string; temperature: number; context_tokens: number; api_key: string };
  enabled: boolean; reachable: boolean; models: { name: string; size_gb?: number; parameters?: string }[]; model_available: boolean; ready: boolean; error: string | null;
}
export interface AiRun {
  running: boolean; status: string; text: string; sources: AiSource[]; steps: AgentStep[]; retrieval: any | null;
  done: { model: string; elapsed_ms: number; grounding: Grounding; cached?: boolean } | null; error: { message: string; hint?: string } | null;
}

const EMPTY: AiRun = { running: false, status: "", text: "", sources: [], steps: [], retrieval: null, done: null, error: null };

function authHeaders(): Record<string, string> {
  let t = "";
  try { t = localStorage.getItem("ctpip.token") || ""; } catch { /* storage unavailable */ }
  return t ? { "Content-Type": "application/json", "X-API-Token": t } : { "Content-Type": "application/json" };
}

/** POST to a streaming endpoint and call onEvent for every server-sent event. */
export async function streamAi(url: string, body: unknown, onEvent: (e: any) => void, signal?: AbortSignal) {
  const r = await fetch(url, { method: "POST", headers: authHeaders(), body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      if (chunk.startsWith("data:")) {
        try { onEvent(JSON.parse(chunk.slice(5).trim())); } catch { /* ignore malformed event */ }
      }
    }
  }
}

/** Run a streaming AI request and keep its state. `start(body)` restarts; `stop()` aborts. */
export function useAiRun(endpoint: string) {
  const [run, setRun] = useState<AiRun>(EMPTY);
  const ctrl = useRef<AbortController | null>(null);
  const stop = useCallback(() => { ctrl.current?.abort(); setRun((r) => ({ ...r, running: false, status: "" })); }, []);
  const start = useCallback((body: unknown) => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setRun({ ...EMPTY, running: true, status: "Starting..." });
    streamAi(endpoint, body, (e) => {
      setRun((r) => {
        switch (e.type) {
          case "status": return { ...r, status: e.message };
          case "sources": return { ...r, sources: e.sources };
          case "retrieval": return { ...r, retrieval: e };
          case "step": return { ...r, steps: [...r.steps, e], status: e.action === "final" ? "Writing the answer..." : `Agent: ${e.action}...` };
          case "token": return { ...r, text: r.text + e.text, status: "" };
          case "done": return { ...r, done: e, running: false, status: "" };
          case "error": return { ...r, error: { message: e.message, hint: e.hint }, running: false, status: "" };
          default: return r;
        }
      });
    }, c.signal)
      .then(() => setRun((r) => ({ ...r, running: false, status: "" })))
      .catch((err) => { if (err.name !== "AbortError") setRun((r) => ({ ...r, running: false, status: "", error: { message: err.message } })); });
  }, [endpoint]);
  useEffect(() => () => ctrl.current?.abort(), []);
  return { run, start, stop };
}

export function useAiStatus() {
  return useQuery<AiStatus>({ queryKey: ["ai-status"], queryFn: () => api.get("/api/ai/status"), refetchInterval: 30_000, staleTime: 10_000 });
}

/** Per-area "Explain with local AI" switch, remembered in this browser. */
export function useAiToggle(area: string, initial = true): [boolean, (v: boolean) => void] {
  const key = `ctpip.ai.${area}`;
  const [on, setOn] = useState<boolean>(() => {
    try { const v = localStorage.getItem(key); return v == null ? initial : v === "1"; } catch { return initial; }
  });
  const set = (v: boolean) => { setOn(v); try { localStorage.setItem(key, v ? "1" : "0"); } catch { /* storage unavailable */ } };
  return [on, set];
}
