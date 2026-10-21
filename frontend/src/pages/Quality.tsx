import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import { PageHeader } from "../App";
import { Bars } from "./Dashboard";
import { Badge, Button, Card, Empty, ErrorBox, Spinner, Tabs } from "../components/ui";
import { api } from "../lib/api";

export default function Quality() {
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Data Quality" subtitle="Reading warnings, look-alike drug names awaiting a human decision, and differences between sources." />
      <div className="flex-1 overflow-auto p-6"><QualityPanel /></div>
    </div>
  );
}

export function QualityPanel() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"overview" | "review" | "conflicts" | "warnings">("overview");
  const [sev, setSev] = useState("warning");
  const sum = useQuery({ queryKey: ["qsum"], queryFn: () => api.get("/api/quality/summary") });
  const review = useQuery({ queryKey: ["review"], queryFn: () => api.get<any[]>("/api/quality/review"), enabled: tab === "review" });
  const conf = useQuery({ queryKey: ["conflicts"], queryFn: () => api.get("/api/quality/conflicts"), enabled: tab === "conflicts" });
  const warns = useQuery({ queryKey: ["warns", sev], queryFn: () => api.get<any[]>(`/api/quality/warnings?severity=${sev}&limit=500`), enabled: tab === "warnings" });
  const decide = useMutation({ mutationFn: ({ id, decision }: { id: string; decision: string }) => api.post(`/api/quality/review/${id}`, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["review"] }) });
  const s = sum.data;
  return (
    <div className="space-y-4">
        <Tabs value={tab} onChange={setTab} tabs={[{ id: "overview", label: "Summary" }, { id: "review", label: "Drug names to review" }, { id: "conflicts", label: "Differences between sources" }, { id: "warnings", label: "Reading warnings" }]} />
        {tab === "overview" && (sum.isLoading ? <Spinner /> : s && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Relationship validation (Layer 3)"><Bars rows={s.relationship_validation.map((r: any) => ({ label: r.status, value: r.n }))} color="#16a34a" /></Card>
            <Card title="Warnings by code"><Bars rows={s.warnings.map((w: any) => ({ label: `${w.severity}: ${w.code}`, value: w.n }))} color="#d97706" /></Card>
            <Card title="Section classification"><Bars rows={s.section_categories.slice(0, 16).map((c: any) => ({ label: c.category, value: c.n }))} color="#0d9488" /></Card>
            <Card title="Documents">
              <Bars rows={[...s.documents.map((d: any) => ({ label: `status: ${d.status}`, value: d.n })), ...s.doc_kinds.map((d: any) => ({ label: `kind: ${d.doc_kind}`, value: d.n })),
                ...s.review.map((r: any) => ({ label: `review: ${r.status}`, value: r.n }))]} color="#475569" />
              {s.documents_without_eligibility_section.length > 0 && <div className="mt-3 text-[12px] text-ink-600"><b>No eligibility section identified ({s.documents_without_eligibility_section.length}):</b>
                {s.documents_without_eligibility_section.slice(0, 20).map((d: any) => <Link key={d.id} to={`/documents/${d.id}`} className="ml-1 text-blue-700 hover:underline">{d.filename}</Link>)}</div>}
            </Card>
          </div>))}
        {tab === "review" && (
          <Card title="Drug-like terms that resemble a known concept (never merged automatically)">
            {review.isLoading && <Spinner />}<ErrorBox error={decide.error} />
            {review.data?.length === 0 && <Empty>No pending review items.</Empty>}
            <table className="w-full text-[12.5px]"><tbody className="divide-y divide-ink-100">{review.data?.map((r) => (
              <tr key={r.id} className="align-top"><td className="py-2 pr-3"><b className="text-ink-800">{r.surface}</b><div className="text-[11px] text-ink-400">{r.filename}</div></td>
                <td className="py-2 pr-3">~ {r.candidate_name} <Badge>{r.score}</Badge></td>
                <td className="max-w-md py-2 pr-3 text-[11.5px] text-ink-500">{r.context}</td>
                <td className="whitespace-nowrap py-2 text-right"><Button size="sm" onClick={() => decide.mutate({ id: r.id, decision: "merge" })}>Same concept — merge</Button>{" "}
                  <Button size="sm" onClick={() => decide.mutate({ id: r.id, decision: "separate" })}>Keep separate</Button></td></tr>))}</tbody></table>
          </Card>)}
        {tab === "conflicts" && (conf.isLoading ? <Spinner /> : conf.data && (
          <div className="space-y-4">
            <p className="text-xs text-ink-500">{conf.data.note}</p>
            <Card title={`Drugs with differing dose statements across protocols (${conf.data.dose_differences.length})`}>
              <div className="space-y-2">{conf.data.dose_differences.map((d: any) => (
                <details key={d.drug_id} className="rounded border border-ink-200 px-3 py-2"><summary className="cursor-pointer text-[13px]"><b>{d.drug}</b> — {d.distinct_doses} distinct doses in {d.protocols} protocols</summary>
                  <ul className="mt-2 space-y-0.5 text-[12px] text-ink-600">{d.specs.map((s: any, i: number) => <li key={i}>{s.label} — <span className="text-ink-400">{s.protocol_name} · p.{s.page}</span></li>)}</ul></details>))}</div>
            </Card>
            <Card title={`Registered trials with several protocol documents (${conf.data.protocol_versions.length})`}>
              {conf.data.protocol_versions.map((v: any) => (
                <div key={v.trial} className="border-b border-ink-100 py-2 text-[12.5px]"><b>{v.trial_name}</b>
                  {v.protocols.map((p: any) => <div key={p.id} className="ml-3 text-ink-600">{p.name} · {p.document_type} {p.version_label ? `· v${p.version_label}` : ""} {p.amendment ? `· amendment ${p.amendment}` : ""} {p.version_date ? `· ${p.version_date}` : ""}</div>)}
                  {v.amends.filter((a: any) => a.newer).length === 0 ? <div className="ml-3 text-[11px] text-amber-700">Version order not stated in all documents — not ordered.</div>
                    : v.amends.filter((a: any) => a.newer).map((a: any, i: number) => <div key={i} className="ml-3 text-[11px] text-ink-500">AMENDS ordered by {a.basis}</div>)}</div>))}
            </Card>
            <Card title={`Endpoint stated as both primary and secondary in one protocol (${conf.data.endpoint_level_differences.length})`}>
              {conf.data.endpoint_level_differences.map((e: any, i: number) => <div key={i} className="text-[12.5px] text-ink-600">{e.protocol_name}: <b>{e.endpoint}</b> (primary p.{e.primary_page}, secondary p.{e.secondary_page})</div>)}
            </Card>
          </div>))}
        {tab === "warnings" && (
          <Card title="Warnings" actions={<Tabs value={sev} onChange={setSev} tabs={[{ id: "error", label: "Errors" }, { id: "warning", label: "Warnings" }, { id: "info", label: "Info" }]} />}>
            {warns.isLoading && <Spinner />}{warns.data?.length === 0 && <Empty>None</Empty>}
            <ul className="divide-y divide-ink-100 text-[12.5px]">{warns.data?.map((w) => (
              <li key={w.id} className="flex gap-2 py-1.5"><Link to={`/documents/${w.doc_id}`} className="w-64 shrink-0 truncate text-blue-700 hover:underline">{w.filename}</Link>
                <span className="w-44 shrink-0 text-ink-500">{w.code}</span><span className="w-12 shrink-0 text-ink-400">{w.page ? `p.${w.page}` : ""}</span><span className="min-w-0 text-ink-700">{w.message}</span></li>))}</ul>
          </Card>)}
      </div>
  );
}
