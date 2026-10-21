// Chat with the local AI about one protocol or all protocols (retrieval-augmented, or a research agent).
import clsx from "clsx";
import { Bot, Send, Trash2, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAiRun } from "../lib/ai";
import { AiNotReady, AiResult } from "./AiAnswer";
import type { SourceRef } from "./SourceViewer";

type Msg = { id: number; role: "user" | "assistant"; content: string; mode?: "rag" | "agent"; history?: { role: string; content: string }[] };

export default function ChatPanel({ docId, docName, suggestions, onSource }: { docId?: string | null; docName?: string; suggestions: string[]; onSource?: (s: SourceRef) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [finals, setFinals] = useState<Record<number, string>>({});
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"rag" | "agent">("rag");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { setMsgs([]); setFinals({}); }, [docId]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length]);

  const send = (text: string) => {
    const t = text.trim();
    if (t.length < 2) return;
    const history: { role: string; content: string }[] = [];
    msgs.forEach((m) => {
      if (m.role === "user") history.push({ role: "user", content: m.content });
      else if (finals[m.id]) history.push({ role: "assistant", content: finals[m.id] });
    });
    const id = Date.now();
    setMsgs((x) => [...x, { id, role: "user", content: t }, { id: id + 1, role: "assistant", content: t, mode, history: history.slice(-6) }]);
    setQ("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 bg-white px-4 py-2">
        <span className="text-[12.5px] text-ink-500">Answer style:</span>
        {(["rag", "agent"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} className={clsx("rounded-full border px-3 py-1 text-[12.5px] font-medium transition",
            mode === m ? "border-violet-600 bg-violet-600 text-white" : "border-ink-200 bg-white text-ink-600 hover:border-ink-300")}>
            {m === "rag" ? "Quick answer" : "Research agent (deeper, slower)"}</button>))}
        <span className="text-[11.5px] text-ink-400">{mode === "rag" ? "Searches the protocol text and answers with sources." : "The AI plans several searches, compares protocols, then answers with sources."}</span>
        {msgs.length > 0 && <button onClick={() => { setMsgs([]); setFinals({}); }} className="ml-auto inline-flex items-center gap-1 text-[12px] text-ink-500 hover:text-ink-800"><Trash2 className="h-3.5 w-3.5" />New conversation</button>}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto bg-ink-50/60 px-4 py-4">
        <AiNotReady />
        {msgs.length === 0 && (
          <div className="mx-auto max-w-3xl rounded-lg border border-ink-200 bg-white p-5">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-ink-800"><Bot className="h-5 w-5 text-violet-600" />
              {docName ? `Ask anything about ${docName}` : "Ask anything about the breast-cancer protocols"}</div>
            <p className="mt-1 text-[13px] text-ink-500">Answers come from a local AI that acts as a clinical-trial protocol expert. It reads only the protocol text, explains medical terms in plain language and shows the exact sources it used.</p>
            <div className="mt-3 flex flex-wrap gap-2">{suggestions.map((s) => (
              <button key={s} onClick={() => send(s)} className="rounded-full border border-ink-200 bg-ink-50 px-3 py-1 text-left text-[12.5px] text-ink-700 hover:border-violet-300 hover:bg-violet-50">{s}</button>))}</div>
          </div>
        )}
        {msgs.map((m) => m.role === "user" ? (
          <div key={m.id} className="ml-auto flex max-w-3xl items-start justify-end gap-2">
            <div className="rounded-lg bg-ink-900 px-3.5 py-2 text-[14px] text-white">{m.content}</div>
            <User className="mt-1.5 h-5 w-5 shrink-0 text-ink-400" />
          </div>
        ) : (
          <div key={m.id} className="mr-auto max-w-4xl">
            <ChatAnswer body={{ question: m.content, history: m.history, doc_id: docId || null, mode: m.mode }} onSource={onSource}
              onFinal={(t) => setFinals((f) => ({ ...f, [m.id]: t }))} />
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="flex gap-2 border-t border-ink-200 bg-white px-4 py-3" onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={docName ? `Ask about this protocol, e.g. "Who can take part?"` : "Ask a question, e.g. \"Which trials allow brain metastases?\""}
          className="flex-1 rounded-md border border-ink-200 px-3 py-2 text-[14px] outline-none ring-violet-500 focus:ring-2" />
        <button className="inline-flex items-center gap-1.5 rounded-md bg-violet-600 px-4 text-[13.5px] font-medium text-white hover:bg-violet-700 disabled:opacity-50" disabled={q.trim().length < 2}>
          <Send className="h-4 w-4" />Ask</button>
      </form>
    </div>
  );
}

function ChatAnswer({ body, onSource, onFinal }: { body: any; onSource?: (s: SourceRef) => void; onFinal: (t: string) => void }) {
  const { run, start, stop } = useAiRun("/api/ai/chat");
  useEffect(() => { start(body); /* eslint-disable-next-line */ }, []);
  useEffect(() => { if (run.done) onFinal(run.text); /* eslint-disable-next-line */ }, [run.done]);
  return <AiResult run={run} title={body.mode === "agent" ? "Research agent" : "Answer"} onSource={onSource} onStop={stop} onRegenerate={() => start(body)} compact />;
}
