import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../App";
import ChatPanel from "../components/ChatPanel";
import SourceViewer, { type SourceRef } from "../components/SourceViewer";
import { api } from "../lib/api";

const ALL_SUGGESTIONS = [
  "Which trials test palbociclib with letrozole, and what dose do they use?",
  "Which studies allow patients with brain metastases?",
  "What does progression-free survival mean, and which trials use it as the main goal?",
  "Which trials are for triple-negative breast cancer and what treatments do they give?",
  "Which protocols monitor the heart (LVEF) and why?",
  "Compare KEYNOTE-355 and PALOMA-3: who can join and what treatment is given?",
];
const DOC_SUGGESTIONS = [
  "Explain this study in simple words.",
  "Who can take part, and who cannot?",
  "What treatment do participants receive, how much and how often?",
  "What side effects are watched and what happens if they occur?",
  "What is the main goal of the study and how is it measured?",
];

export default function AssistantPage() {
  const [params, setParams] = useSearchParams();
  const docId = params.get("doc") || "";
  const [filter, setFilter] = useState("");
  const [source, setSource] = useState<SourceRef | null>(null);
  const docs = useQuery({ queryKey: ["docs-mini"], queryFn: () => api.get("/api/documents?limit=1000&status=processed") });
  const items = ((docs.data?.items || []) as any[]).filter((d) => !filter || `${d.filename} ${d.title} ${d.nct_id}`.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => a.filename.localeCompare(b.filename, undefined, { numeric: true }));
  const doc = (docs.data?.items || []).find((d: any) => d.id === docId);
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Ask AI" subtitle="A local clinical-trial protocol expert. Ask about one protocol or all of them; every answer shows its sources." />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-72 shrink-0 flex-col border-r border-ink-200 bg-white">
          <div className="space-y-2 border-b border-ink-100 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Ask about</div>
            <button onClick={() => setParams({})} className={`w-full rounded-md border px-3 py-2 text-left text-[13px] ${!docId ? "border-violet-500 bg-violet-50 font-medium text-violet-800" : "border-ink-200 text-ink-700 hover:bg-ink-50"}`}>All protocols ({docs.data?.total ?? "..."})</button>
            <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
              <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Or pick one protocol..." className="w-full rounded-md border border-ink-200 py-1.5 pl-8 pr-2 text-[13px]" /></div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">{items.map((d) => (
            <button key={d.id} onClick={() => setParams({ doc: d.id })} className={`block w-full border-b border-ink-50 px-3 py-1.5 text-left text-[12.5px] ${d.id === docId ? "bg-violet-50 text-violet-900" : "text-ink-700 hover:bg-ink-50"}`}>
              <span className="block truncate">{d.filename}</span><span className="text-[11px] text-ink-400">{d.nct_id || ""} {d.phase || ""}</span></button>))}</div>
        </aside>
        <div className="min-w-0 flex-1">
          <ChatPanel docId={docId || null} docName={doc?.filename} suggestions={docId ? DOC_SUGGESTIONS : ALL_SUGGESTIONS} onSource={setSource} />
        </div>
      </div>
      <SourceViewer source={source} onClose={() => setSource(null)} />
    </div>
  );
}
