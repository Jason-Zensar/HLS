import { useQuery } from "@tanstack/react-query";
import { FileText, Search } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../App";
import { AiAnswer, AiToggle } from "../components/AiAnswer";
import { useAiToggle } from "../lib/ai";
import SourceViewer, { type SourceRef } from "../components/SourceViewer";
import { Badge, Empty, ErrorBox, Spinner } from "../components/ui";
import { api, enc } from "../lib/api";

const CATS = ["", "synopsis", "inclusion_criteria", "exclusion_criteria", "eligibility", "dosing", "treatment_arms", "study_design", "primary_endpoints", "secondary_endpoints",
  "endpoints", "objectives", "adverse_events", "safety_monitoring", "schedule_of_assessments", "biomarkers", "statistics", "follow_up", "background"];

export default function EvidenceExplorer({ embedded }: { embedded?: boolean } = {}) {
  const [aiOn, setAiOn] = useAiToggle("text-search");
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [cat, setCat] = useState("");
  const [doc, setDoc] = useState("");
  const [source, setSource] = useState<SourceRef | null>(null);
  const docs = useQuery({ queryKey: ["docs-mini"], queryFn: () => api.get("/api/documents?limit=1000") });
  const res = useQuery({ queryKey: ["ev", term, cat, doc], queryFn: () => api.get<any[]>(`/api/evidence/search?q=${enc(term)}&section_category=${cat}&doc_id=${doc}&limit=80`), enabled: term.length >= 2 });
  return (
    <div className="flex h-full flex-col">
      {!embedded && <PageHeader title="Evidence Explorer" subtitle="Full-text discovery over every extracted passage with exact page references. Lexical matches are evidence to inspect — they never create graph relationships." />}
      <div className="border-b border-ink-200 bg-white px-6 py-3">
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setTerm(q.trim()); }}>
          <div className="relative min-w-[320px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. LVEF 50%, ECOG 0 or 1, brain metastases, 21-day cycle" className="w-full rounded-md border border-ink-200 py-2 pl-9 pr-3 text-[13.5px]" /></div>
          <select value={cat} onChange={(e) => setCat(e.target.value)} className="rounded-md border border-ink-200 bg-white px-2 text-[13px]">{CATS.map((c) => <option key={c} value={c}>{c || "Any section"}</option>)}</select>
          <select value={doc} onChange={(e) => setDoc(e.target.value)} className="max-w-xs rounded-md border border-ink-200 bg-white px-2 text-[13px]"><option value="">All documents</option>
            {docs.data?.items?.map((d: any) => <option key={d.id} value={d.id}>{d.filename.slice(0, 60)}</option>)}</select>
          <button className="rounded-md bg-ink-900 px-3 text-[13px] font-medium text-white">Search</button>
          <AiToggle on={aiOn} onChange={setAiOn} label="Summarise with local AI" />
        </form>
      </div>
      <div className="flex-1 overflow-auto p-6">
        {!term && <Empty>Search the indexed passages. Each result links to the highlighted region on the original PDF page.</Empty>}
        {res.isLoading && <Spinner label="Searching" />}
        <ErrorBox error={res.error} />
        {aiOn && term && res.data && res.data.length > 0 && <div className="mb-4"><AiAnswer endpoint="/api/ai/explain/evidence" body={{ q: term, doc_id: doc, section_category: cat }} runKey={`${term}|${doc}|${cat}`} title="AI summary of the matching passages" onSource={setSource} /></div>}
        {res.data && <div className="mb-2 text-xs text-ink-500">{res.data.length} passages</div>}
        <div className="space-y-2">{res.data?.map((r) => (
          <div key={r.chunk_id} className="rounded-md border border-ink-200 bg-white px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-500">
              <span className="font-medium text-ink-800">{r.filename}</span>{r.nct_id && <Badge tone="blue">{r.nct_id}</Badge>}<span>p.{r.page_start}{r.page_end !== r.page_start ? `–${r.page_end}` : ""}</span>
              <Badge>{r.section_category}</Badge><span className="truncate">{r.section_title}</span><Badge>{r.chunk_type}</Badge>
              <button className="ml-auto inline-flex items-center gap-1 rounded border border-ink-200 px-1.5 py-0.5 text-ink-700 hover:bg-ink-50" onClick={() => setSource({ docId: r.doc_id, page: r.page_start, chunkId: r.chunk_id, title: r.title })}><FileText className="h-3 w-3" />View source</button>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-700">{r.snippet.split(/(\[\[.*?\]\])/g).map((p: string, i: number) => p.startsWith("[[") ? <mark key={i} className="rounded bg-amber-100 px-0.5">{p.slice(2, -2)}</mark> : p)}</p>
          </div>))}</div>
      </div>
      <SourceViewer source={source} onClose={() => setSource(null)} />
    </div>
  );
}
