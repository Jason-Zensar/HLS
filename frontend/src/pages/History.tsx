import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../App";
import { Card, Empty, Spinner, StatusBadge, Tabs, fmtTime } from "../components/ui";
import { api } from "../lib/api";

export default function HistoryPage() {
  const [tab, setTab] = useState<"queries" | "audit">("queries");
  const [open, setOpen] = useState<string | null>(null);
  const qs = useQuery({ queryKey: ["hq"], queryFn: () => api.get<any[]>("/api/history/queries?limit=200") });
  const au = useQuery({ queryKey: ["ha"], queryFn: () => api.get<any[]>("/api/history/audit?limit=300"), enabled: tab === "audit" });
  const detail = useQuery({ queryKey: ["hqd", open], queryFn: () => api.get(`/api/history/queries/${open}`), enabled: !!open });
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="History & Audit" subtitle="Every query is stored with its plan, executed graph patterns, validation result and full response; processing events are logged." />
      <div className="flex-1 space-y-4 overflow-auto p-6">
        <Tabs value={tab} onChange={setTab} tabs={[{ id: "queries", label: "Query history" }, { id: "audit", label: "Processing audit log" }]} />
        {tab === "queries" && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_520px]">
            <Card bodyClass="p-0">
              {qs.isLoading && <div className="p-4"><Spinner /></div>}
              {qs.data?.length === 0 && <div className="p-4"><Empty>No queries yet</Empty></div>}
              <table className="w-full text-[12.5px]"><tbody className="divide-y divide-ink-100">{qs.data?.map((q) => (
                <tr key={q.id} onClick={() => setOpen(q.id)} className={`cursor-pointer hover:bg-ink-50 ${open === q.id ? "bg-blue-50" : ""}`}>
                  <td className="w-40 px-3 py-2 text-ink-400">{fmtTime(q.ts)}</td><td className="px-3 py-2 text-ink-800">{q.question}</td>
                  <td className="px-3 py-2 text-ink-500">{q.intent}</td><td className="px-3 py-2"><StatusBadge status={q.validation_status} /></td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink-400">{q.n_nodes}n · {q.n_edges}e · {Math.round(q.latency_ms)}ms</td></tr>))}</tbody></table>
            </Card>
            <Card title="Stored plan & audit record">
              {!open && <Empty>Select a query</Empty>}
              {detail.isLoading && <Spinner />}
              {detail.data && (<div className="space-y-2 text-[12px]">
                <Link className="text-blue-700 hover:underline" to={`/query?q=${encodeURIComponent(detail.data.question)}`}>Re-run this query →</Link>
                <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded bg-ink-50 p-2 font-mono text-[11px] text-ink-700">{JSON.stringify({ plan: detail.data.plan, validation: detail.data.response?.validation_status,
                  issues: detail.data.response?.validation_issues, answer: detail.data.response?.answer_summary?.text, evidence_passages: detail.data.response?.evidence_passages?.length }, null, 2)}</pre>
              </div>)}
            </Card>
          </div>)}
        {tab === "audit" && (
          <Card bodyClass="p-0"><ul className="divide-y divide-ink-100 text-[12.5px]">{au.data?.map((a) => (
            <li key={a.id} className="flex gap-3 px-3 py-1.5"><span className="w-40 shrink-0 text-ink-400">{fmtTime(a.ts)}</span><span className="w-40 shrink-0 text-ink-500">{a.kind}</span>
              {a.doc_id ? <Link to={`/documents/${a.doc_id}`} className="min-w-0 text-ink-700 hover:underline">{a.message}</Link> : <span className="min-w-0 text-ink-700">{a.message}</span>}</li>))}</ul></Card>)}
      </div>
    </div>
  );
}
