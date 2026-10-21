import { useMutation, useQuery } from "@tanstack/react-query";
import { FileText, X } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../App";
import { AiAnswer, AiToggle } from "../components/AiAnswer";
import { useAiToggle } from "../lib/ai";
import SourceViewer, { type SourceRef } from "../components/SourceViewer";
import { Badge, Button, Card, Empty, ErrorBox, Spinner } from "../components/ui";
import { api } from "../lib/api";

const TONE: Record<string, any> = { same: "green", similar: "blue", different: "violet", conflicting: "red", unavailable: "amber", single: "slate" };

export default function ComparePage() {
  const [aiOn, setAiOn] = useAiToggle("compare");
  const docs = useQuery({ queryKey: ["docs-mini"], queryFn: () => api.get("/api/documents?limit=1000&status=processed") });
  const [picked, setPicked] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [source, setSource] = useState<SourceRef | null>(null);
  const cmp = useMutation({ mutationFn: (ids: string[]) => api.post("/api/compare", { protocol_ids: ids }) });
  const items = (docs.data?.items || []).filter((d: any) => !filter || d.filename.toLowerCase().includes(filter.toLowerCase()));
  const r = cmp.data;
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Protocol Comparison" subtitle="Field-by-field comparison of 2–4 protocols. Every value carries its own source passage; missing information is reported as unavailable, never as exclusion." />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-72 shrink-0 flex-col border-r border-ink-200 bg-white">
          <div className="space-y-2 border-b border-ink-100 p-3">
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter protocols…" className="w-full rounded-md border border-ink-200 px-2 py-1.5 text-[13px]" />
            <div className="flex flex-wrap gap-1">{picked.map((p) => <Badge key={p} tone="blue">{docs.data?.items.find((d: any) => d.id === p)?.filename.slice(0, 28)}<button onClick={() => setPicked((s) => s.filter((x) => x !== p))}><X className="h-3 w-3" /></button></Badge>)}</div>
            <AiToggle on={aiOn} onChange={setAiOn} label="Explain the differences with AI" />
            <Button variant="primary" className="w-full justify-center" disabled={picked.length < 2 || cmp.isPending} onClick={() => cmp.mutate(picked)}>Compare {picked.length} protocols</Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">{items.map((d: any) => (
            <label key={d.id} className="flex cursor-pointer items-start gap-2 border-b border-ink-50 px-3 py-1.5 text-[12px] hover:bg-ink-50">
              <input type="checkbox" checked={picked.includes(d.id)} disabled={!picked.includes(d.id) && picked.length >= 4}
                onChange={(e) => setPicked((s) => (e.target.checked ? [...s, d.id] : s.filter((x) => x !== d.id)))} className="mt-0.5" />
              <span className="min-w-0"><span className="block truncate text-ink-800">{d.filename}</span><span className="text-[10.5px] text-ink-400">{d.nct_id || d.sponsor_protocol_code || ""} {d.phase || ""}</span></span>
            </label>))}</div>
        </aside>
        <div className="min-w-0 flex-1 overflow-auto p-6">
          {!r && !cmp.isPending && <Empty>Select two to four protocols on the left.</Empty>}
          {cmp.isPending && <Spinner label="Comparing" />}
          <ErrorBox error={cmp.error} />
          {r && (
            <div className="space-y-3">
              {aiOn && <AiAnswer endpoint="/api/ai/explain/compare" body={{ protocol_ids: r.protocols.map((p: any) => p.id) }} runKey={r.protocols.map((p: any) => p.id).join("|")} title="AI explanation of the comparison" onSource={setSource} />}
              <p className="text-xs text-ink-500">{r.note}{r.same_trial && <b className="ml-1 text-amber-700">These documents are versions of the same registered trial — differences may reflect amendments.</b>}</p>
              {r.shared_entities.length > 0 && <Card title={`Entities shared by all selected protocols (${r.shared_entities.length})`}><div className="flex flex-wrap gap-1">{r.shared_entities.map((e: any) => <Badge key={e.id}>{e.name}</Badge>)}</div></Card>}
              <div className="overflow-auto rounded-lg border border-ink-200 bg-white">
                <table className="w-full table-fixed text-[12px]">
                  <thead className="bg-ink-50 text-left">
                    <tr><th className="w-44 px-3 py-2 text-[11px] uppercase text-ink-500">Field</th>
                      {r.protocols.map((p: any) => <th key={p.id} className="px-3 py-2 align-top font-semibold text-ink-800">{p.title}<div className="font-normal text-ink-400">{p.nct || p.document?.nct_id || ""} {p.phase || ""} {p.version ? `· v${p.version}` : ""} {p.amendment ? `· am.${p.amendment}` : ""}</div></th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {r.fields.map((f: any) => (
                      <tr key={f.field} className="align-top">
                        <td className="px-3 py-2"><div className="font-medium text-ink-700">{f.label}</div><Badge tone={TONE[f.status]} className="mt-1">{f.status}</Badge>
                          {f.detail && <div className="mt-1 text-[10.5px] leading-snug text-ink-400">{f.detail}</div>}</td>
                        {r.protocols.map((p: any) => {
                          const vals = f.values[p.id] || [];
                          return (
                            <td key={p.id} className="px-3 py-2">
                              {vals.length === 0 ? <span className="italic text-ink-300">not found in document</span> : (
                                <ul className="space-y-1">{vals.slice(0, f.field === "inclusion" || f.field === "exclusion" ? 40 : 15).map((v: any, i: number) => (
                                  <li key={i} className="group flex gap-1">
                                    <span className={`min-w-0 flex-1 ${["inclusion", "exclusion", "safety_rules", "follow_up"].includes(f.field) ? "line-clamp-3" : ""} text-ink-700`} title={v.evidence.quote}>{v.value}</span>
                                    <button title={`p.${v.evidence.page} — view source`} className="shrink-0 text-ink-300 hover:text-ink-700"
                                      onClick={() => setSource({ docId: v.evidence.doc_id, page: v.evidence.page, quote: v.evidence.quote })}><FileText className="h-3.5 w-3.5" /></button>
                                  </li>))}</ul>)}
                            </td>);
                        })}
                      </tr>))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
      <SourceViewer source={source} onClose={() => setSource(null)} />
    </div>
  );
}
