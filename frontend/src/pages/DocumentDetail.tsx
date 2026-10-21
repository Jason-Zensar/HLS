import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { BookOpen, ExternalLink, FileText, GraduationCap, MessageSquare, Network, RefreshCw, Sparkles, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { PageHeader } from "../App";
import { AiAnswer, AiNotReady } from "../components/AiAnswer";
import ChatPanel from "../components/ChatPanel";
import SourceViewer, { type SourceRef } from "../components/SourceViewer";
import { Badge, Button, Card, Empty, Spinner, StatusBadge, fmtTime } from "../components/ui";
import { api, pdfUrl } from "../lib/api";

type Tab = "overview" | "ai" | "ask" | "document" | "technical";
const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: "overview", label: "Overview (plain language)", icon: BookOpen },
  { id: "ai", label: "AI explanation", icon: Sparkles },
  { id: "ask", label: "Ask questions", icon: MessageSquare },
  { id: "document", label: "Original document", icon: FileText },
  { id: "technical", label: "Technical details", icon: Wrench },
];

export default function DocumentDetail() {
  const { docId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const setTab = (t: Tab) => setParams({ tab: t }, { replace: true });
  const [source, setSource] = useState<SourceRef | null>(null);
  const doc = useQuery({ queryKey: ["doc", docId], queryFn: () => api.get(`/api/documents/${docId}`), refetchInterval: (q) => (q.state.data?.status === "processed" ? false : 5000) });
  const brief = useQuery({ queryKey: ["brief", docId], queryFn: () => api.get(`/api/ai/protocol/${docId}/brief`), enabled: doc.data?.status === "processed" });
  const d = doc.data;
  if (doc.isLoading) return <div className="p-6"><Spinner label="Loading protocol" /></div>;
  if (!d) return <div className="p-6"><Empty>Protocol not found</Empty></div>;
  const b = brief.data;
  return (
    <div className="flex h-full flex-col">
      <PageHeader title={d.filename.replace(/\.pdf$/i, "")} subtitle={b?.one_liner || d.title}
        actions={<>
          <a href={pdfUrl(docId)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border border-ink-200 bg-white px-3 py-1.5 text-[13px] hover:bg-ink-50"><ExternalLink className="h-3.5 w-3.5" />Open PDF</a>
          <Link to={`/graph?focus=${encodeURIComponent(d.protocol_node_id)}`} className="inline-flex items-center gap-1 rounded-md border border-ink-200 bg-white px-3 py-1.5 text-[13px] hover:bg-ink-50"><Network className="h-3.5 w-3.5" />Show in graph</Link>
        </>} />
      <div className="flex gap-1 border-b border-ink-200 bg-white px-6">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)} className={clsx("flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px] font-medium transition",
            tab === id ? "border-violet-600 text-violet-800" : "border-transparent text-ink-500 hover:text-ink-800")}><Icon className="h-4 w-4" />{label}</button>))}
      </div>
      <div className={clsx("min-h-0 flex-1", tab === "ask" ? "" : "overflow-auto p-6")}>
        {d.status !== "processed" && <div className="mb-4 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">This protocol is {d.status}. The study views appear when processing is finished.</div>}
        {tab === "overview" && (brief.isLoading ? <Spinner label="Building the overview" /> : b && <Overview b={b} onSource={setSource} />)}
        {tab === "ai" && (
          <div className="mx-auto max-w-4xl space-y-3">
            <AiNotReady />
            <p className="text-[13px] text-ink-500">A local AI acting as a clinical-trial protocol expert explains this protocol for a non-medical reader. It uses only this protocol's facts and key sections, and cites them. The explanation is saved, so it opens instantly next time.</p>
            <AiAnswer endpoint="/api/ai/explain/protocol" body={{ doc_id: docId }} regenerateBody={{ doc_id: docId, refresh: true }} runKey={docId} title="Protocol explained in plain language" onSource={setSource} />
          </div>
        )}
        {tab === "ask" && <ChatPanel docId={docId} docName={d.filename} onSource={setSource}
          suggestions={["Explain this study in simple words.", "Who can take part, and who cannot?", "What treatment do participants receive, how much and how often?", "What side effects are watched?", "What is the main goal and how is it measured?"]} />}
        {tab === "document" && <DocumentStructure docId={docId} onSource={setSource} />}
        {tab === "technical" && <Technical d={d} docId={docId} onSource={setSource} />}
      </div>
      <SourceViewer source={source} onClose={() => setSource(null)} />
    </div>
  );
}

function PageLink({ ev, onSource }: { ev: any; onSource: (s: SourceRef) => void }) {
  if (!ev?.page) return null;
  return <button title="Show this on the original page" onClick={() => onSource({ docId: ev.doc_id, page: ev.page, chunkId: ev.chunk_id || undefined, quote: ev.quote || undefined })}
    className="ml-1 inline-flex shrink-0 items-center gap-0.5 rounded px-1 text-[11px] text-ink-400 hover:bg-ink-100 hover:text-ink-700"><FileText className="h-3 w-3" />p.{ev.page}</button>;
}

function Overview({ b, onSource }: { b: any; onSource: (s: SourceRef) => void }) {
  return (
    <div className="mx-auto max-w-6xl space-y-4">
      {!b.graph_available && <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-amber-800">The graph database is offline, so only document details are shown.</div>}
      <div className="rounded-lg border border-ink-200 bg-white p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">In one sentence</div>
        <p className="mt-1 text-[16px] leading-snug text-ink-900">{b.one_liner}</p>
        <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2 xl:grid-cols-3">
          {b.facts.map((f: any) => (
            <div key={f.label} className="text-[13px]"><div className="text-[11.5px] font-medium text-ink-400">{f.label}</div>
              <div className="text-ink-800">{f.value}</div>{f.explain && <div className="text-[12px] italic text-ink-500">{f.explain}</div>}</div>))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {b.sections.filter((s: any) => s.groups.length).map((s: any) => (
          <Card key={s.key} title={s.title}>
            <div className="space-y-3">{s.groups.map((g: any) => (
              <div key={g.label}>
                <div className="mb-1 text-[11.5px] font-semibold uppercase tracking-wide text-ink-400">{g.label}{g.total > g.items.length ? ` (showing ${g.items.length} of ${g.total})` : ""}</div>
                <ul className="space-y-1">{g.items.map((it: any, i: number) => (
                  <li key={i} className="flex items-start gap-2 text-[13px] text-ink-700"><span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
                    <span className="min-w-0 flex-1">{it.text}</span><PageLink ev={it.evidence} onSource={onSource} /></li>))}</ul>
              </div>))}</div>
          </Card>))}
      </div>
      {b.drug_reference?.length > 0 && (
        <Card title="The treatments explained">
          <ul className="space-y-1.5 text-[13px]">{b.drug_reference.map((r: any) => (
            <li key={r.drug}><b className="text-ink-900">{r.drug}</b>{r.classes.length ? <span className="text-ink-500"> ({r.classes.join(", ")})</span> : null}
              {r.explanation && <span className="text-ink-700"> - {r.explanation.split("; ").map((x: string) => x.split(": ").slice(1).join(": ")).join("; ")}</span>}
              {r.other_names?.length > 0 && <span className="text-[12px] text-ink-400"> · also called {r.other_names.join(", ")}</span>}</li>))}</ul>
          <p className="mt-2 text-[11.5px] text-ink-400">General drug knowledge from the built-in terminology, not from this protocol.</p>
        </Card>
      )}
      {b.glossary?.length > 0 && (
        <Card title={<span className="flex items-center gap-1.5"><GraduationCap className="h-4 w-4 text-violet-600" />Words in this protocol, explained</span>}>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2">{b.glossary.map((g: any) => (
            <div key={g.term} className="text-[13px]"><dt className="font-semibold text-ink-800">{g.term}</dt><dd className="text-ink-600">{g.explanation}</dd></div>))}</dl>
        </Card>
      )}
      {b.key_passages?.length > 0 && (
        <details className="rounded-lg border border-ink-200 bg-white px-4 py-3">
          <summary className="cursor-pointer text-[13px] font-semibold text-ink-700">Read the protocol's own summary sections ({b.key_passages.length} passages)</summary>
          <div className="mt-3 space-y-2">{b.key_passages.map((k: any) => (
            <div key={k.chunk_id} className="rounded border border-ink-100 px-3 py-2 text-[13px]">
              <div className="mb-1 flex items-center text-[11.5px] text-ink-400">{k.section}<PageLink ev={{ doc_id: b.doc.id, page: k.page, chunk_id: k.chunk_id }} onSource={onSource} /></div>
              <p className="whitespace-pre-wrap leading-relaxed text-ink-700">{k.text}</p></div>))}</div>
        </details>
      )}
    </div>
  );
}

function DocumentStructure({ docId, onSource }: { docId: string; onSource: (s: SourceRef) => void }) {
  const [section, setSection] = useState("");
  const sections = useQuery({ queryKey: ["sections", docId], queryFn: () => api.get<any[]>(`/api/documents/${docId}/sections`) });
  const chunks = useQuery({ queryKey: ["chunks", docId, section], queryFn: () => api.get<any[]>(`/api/documents/${docId}/chunks?section_id=${section}&limit=300`), enabled: !!section });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[420px_1fr]">
      <Card title="Table of contents (detected)" bodyClass="p-0">
        <div className="max-h-[70vh] overflow-auto py-1">
          {sections.data?.map((s) => (
            <button key={s.id} onClick={() => setSection(s.id)} style={{ paddingLeft: 10 + Math.min(s.level, 5) * 12 }}
              className={`flex w-full items-center gap-2 py-1 pr-3 text-left text-[12.5px] hover:bg-ink-50 ${section === s.id ? "bg-violet-50" : ""}`}>
              <span className="min-w-0 flex-1 truncate text-ink-700">{s.number} {s.title}</span>
              <span className={`shrink-0 rounded px-1 text-[10px] ${s.category === "unknown" ? "bg-ink-100 text-ink-400" : "bg-teal-50 text-teal-700"}`}>{s.category.replace(/_/g, " ")}</span>
              <span className="shrink-0 text-[10px] tabular-nums text-ink-400">p.{s.page_start}</span>
            </button>))}
        </div>
      </Card>
      <Card title={section ? "Text of this section" : "Pick a section on the left"}>
        {!section && <Empty>Choose a section to read its text. Each passage links to the original PDF page.</Empty>}
        {chunks.isLoading && <Spinner />}
        <div className="space-y-2">{chunks.data?.map((c) => (
          <div key={c.id} className="rounded border border-ink-200 px-3 py-2">
            <div className="mb-1 flex items-center gap-2 text-[11px] text-ink-500"><span>p.{c.page_start}{c.page_end !== c.page_start ? `-${c.page_end}` : ""}</span>
              <button className="ml-auto inline-flex items-center gap-1 rounded border border-ink-200 px-1.5 py-0.5 text-ink-700 hover:bg-ink-50" onClick={() => onSource({ docId, page: c.page_start, chunkId: c.id })}><FileText className="h-3 w-3" />View on page</button></div>
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-700">{c.text}</p>
          </div>))}</div>
      </Card>
    </div>
  );
}

function Technical({ d, docId, onSource }: { d: any; docId: string; onSource: (s: SourceRef) => void }) {
  const [sub, setSub] = useState<"tables" | "entities" | "warnings">("warnings");
  const tables = useQuery({ queryKey: ["tables", docId], queryFn: () => api.get<any[]>(`/api/documents/${docId}/tables`), enabled: sub === "tables" });
  const ents = useQuery({ queryKey: ["dents", docId], queryFn: () => api.get<any[]>(`/api/documents/${docId}/entities`), enabled: sub === "entities" });
  const reprocess = useMutation({ mutationFn: () => api.post(`/api/documents/${docId}/reprocess`) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <StatusBadge status={d.status} /><Badge>stage: {d.stage}</Badge><Badge>{d.page_count} pages</Badge><Badge>{d.doc_kind}</Badge>
        {d.nct_id && <Badge tone="blue">{d.nct_id}</Badge>}{d.sponsor_protocol_code && <Badge>code {d.sponsor_protocol_code}</Badge>}
        {d.version_label && <Badge>version {d.version_label}</Badge>}{d.amendment && <Badge>amendment {d.amendment}</Badge>}{d.version_date && <Badge>dated {d.version_date}</Badge>}
        <Badge>{d.document_type}</Badge><Badge>{d.section_count} sections · {d.chunk_count} passages · {d.table_count} tables</Badge>
        <Badge tone="green">{d.entity_count} entities · {d.relationship_count} relationships</Badge>
        <span className="text-ink-400">uploaded {fmtTime(d.uploaded_at)} · processed {fmtTime(d.processed_at)}</span>
        <Button size="sm" className="ml-auto" onClick={() => confirm("Re-read this PDF from scratch?") && reprocess.mutate()}><RefreshCw className="h-3.5 w-3.5" />Reprocess</Button>
      </div>
      <div className="flex gap-1">{(["warnings", "tables", "entities"] as const).map((t) => (
        <button key={t} onClick={() => setSub(t)} className={clsx("rounded px-2.5 py-1 text-xs font-medium", sub === t ? "bg-ink-800 text-white" : "bg-ink-100 text-ink-600")}>{t === "warnings" ? `Warnings (${d.warnings.length})` : t[0].toUpperCase() + t.slice(1)}</button>))}</div>
      {sub === "warnings" && (
        <Card title="Reading and validation warnings">
          {!d.warnings.length && <Empty>No warnings</Empty>}
          <ul className="divide-y divide-ink-100 text-[12.5px]">{d.warnings.map((w: any, i: number) => (
            <li key={i} className="flex gap-2 py-1.5"><Badge tone={w.severity === "error" ? "red" : w.severity === "warning" ? "amber" : "slate"}>{w.severity}</Badge>
              <span className="w-40 shrink-0 text-ink-500">{w.code}</span><span className="w-14 shrink-0 text-ink-400">{w.page ? `p.${w.page}` : ""}</span><span className="text-ink-700">{w.message}</span></li>))}</ul>
        </Card>)}
      {sub === "tables" && (tables.isLoading ? <Spinner /> : !tables.data?.length ? <Empty>No tables detected</Empty> : (
        <div className="space-y-4">{tables.data.map((t) => (
          <Card key={t.id} title={<span>{t.title || "Untitled table"} <span className="font-normal text-ink-400">· p.{t.page} · {t.n_rows}x{t.n_cols}</span></span>}
            actions={<Button size="sm" onClick={() => onSource({ docId, page: t.page })}>View page</Button>}>
            <div className="max-h-80 overflow-auto"><table className="text-[11.5px]"><tbody>{t.cells.slice(0, 60).map((r: string[], i: number) => (
              <tr key={i} className={i === 0 ? "bg-ink-50 font-medium" : ""}>{r.map((c, j) => <td key={j} className="border border-ink-100 px-1.5 py-1 align-top">{c}</td>)}</tr>))}</tbody></table></div>
          </Card>))}</div>))}
      {sub === "entities" && (
        <Card title="Items mentioned (with number of mentions)">
          <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">{ents.data?.map((e) => (
            <Link key={e.entity_id} to={`/graph?focus=${encodeURIComponent(e.entity_id)}`} className="flex items-center justify-between gap-2 border-b border-ink-100 py-1 text-[12.5px] hover:bg-ink-50">
              <span className="truncate text-ink-700">{e.entity_id}</span><span className="shrink-0 text-ink-400">{e.mentions}x · p.{e.first_page}</span></Link>))}</div>
        </Card>)}
    </div>
  );
}
