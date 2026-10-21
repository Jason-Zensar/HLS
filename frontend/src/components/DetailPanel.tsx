import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileText, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api, enc, type GEdge, type GNode } from "../lib/api";
import { GROUP_COLOR, prettyRel } from "../lib/graphStyle";
import type { SourceRef } from "./SourceViewer";
import { Badge, Button, Spinner, SupportBadge } from "./ui";

const KEY_PROPS = ["title", "nct_id", "phase", "sponsor", "version_label", "version_date", "amendment", "document_type", "dose_value", "dose_unit", "frequency",
  "route", "length_days", "kind", "number", "page", "canonical_source", "candidate_match", "candidate_score"];

export function NodeDetail({ node, onClose, onView, onExpand }: { node: GNode; onClose: () => void; onView: (s: SourceRef) => void; onExpand?: (n: GNode) => void }) {
  const q = useQuery({ queryKey: ["entity", node.id], queryFn: () => api.get(`/api/entities/${enc(node.id)}`) });
  const d = q.data;
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between gap-2 border-b border-ink-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink-400">
            <span className="h-2 w-2 rounded-full" style={{ background: GROUP_COLOR[node.group] }} />{node.type}
            {node.scope === "document" && <Badge>protocol-specific</Badge>}
          </div>
          <h3 className="mt-1 text-[14px] font-semibold leading-snug text-ink-900">{node.name}</h3>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-3 text-[13px]">
        {onExpand && <div className="flex gap-2"><Button size="sm" onClick={() => onExpand(node)}>Expand neighbourhood</Button>
          {node.props?.doc_id && node.type === "Protocol" && <Link className="inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-1 text-xs hover:bg-ink-50" to={`/documents/${node.props.doc_id}`}>Open document <ExternalLink className="h-3 w-3" /></Link>}</div>}
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[12px]">
          <dt className="text-ink-400">Canonical id</dt><dd className="break-all font-mono text-[11px] text-ink-600">{node.id}</dd>
          <dt className="text-ink-400">Resolution</dt><dd>{d?.resolution_status || node.props?.resolution_status || (node.scope === "document" ? "document-specific" : "—")}</dd>
          {KEY_PROPS.filter((k) => node.props?.[k] != null && node.props?.[k] !== "").map((k) => (
            <><dt key={k + "t"} className="text-ink-400">{k.replace(/_/g, " ")}</dt><dd key={k + "d"} className="text-ink-700">{String(node.props[k])}</dd></>
          ))}
        </dl>
        {node.props?.text && <div><Sub>Text</Sub><p className="whitespace-pre-wrap rounded bg-ink-50 px-2 py-1.5 text-[12px] leading-relaxed text-ink-700">{node.props.text}</p></div>}
        {q.isLoading && <Spinner label="Loading entity" />}
        {d && (
          <>
            {d.aliases?.length > 0 && <div><Sub>Aliases & original mentions</Sub><div className="flex flex-wrap gap-1">{d.aliases.slice(0, 30).map((a: string) => <Badge key={a}>{a}</Badge>)}
              {d.document_aliases?.map((a: any) => <Badge key={a.alias} tone="violet" title={`learned from ${a.source}`}>{a.alias}</Badge>)}</div></div>}
            {d.connections?.length > 0 && <div><Sub>Connections</Sub><div className="flex flex-wrap gap-1">{d.connections.slice(0, 16).map((c: any, i: number) =>
              <Badge key={i} tone="slate">{c.outgoing ? "→" : "←"} {prettyRel(c.type)} · {c.n}</Badge>)}</div></div>}
            {d.protocols?.length > 0 && <div><Sub>Source protocols ({d.protocols.length})</Sub>
              <ul className="space-y-1">{d.protocols.slice(0, 25).map((p: any) => (
                <li key={p.id} className="rounded border border-ink-100 px-2 py-1.5">
                  <Link to={`/documents/${p.doc_id}`} className="text-[12px] font-medium text-ink-800 hover:underline">{p.name?.slice(0, 110)}</Link>
                  <div className="mt-0.5 flex flex-wrap gap-1 text-[11px] text-ink-500">{p.nct_id && <Badge tone="blue">{p.nct_id}</Badge>}{p.relationships.map((r: string) => <Badge key={r}>{prettyRel(r)}</Badge>)}
                    {p.pages?.filter(Boolean).length > 0 && <span>p. {p.pages.filter(Boolean).join(", ")}</span>}</div>
                </li>))}</ul></div>}
            {d.claims?.length > 0 && <div><Sub>Supporting claims</Sub>
              <ul className="space-y-1.5">{d.claims.slice(0, 20).map((c: any) => (
                <li key={c.claim_id + c.edge_id} className="rounded border border-ink-100 px-2 py-1.5 text-[12px]">
                  <div className="text-ink-700"><span className="font-medium">{c.subject?.slice(0, 50)}</span> <span className="text-ink-400">—{prettyRel(c.predicate)}→</span> <span className="font-medium">{c.object?.slice(0, 50)}</span></div>
                  <div className="mt-1 line-clamp-3 text-ink-600">“{c.quote}”</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-500">
                    <Badge tone={c.validation_status === "validated" ? "green" : "amber"}>{c.validation_status}</Badge>
                    <span>{c.assertion_type}</span><span>conf {c.confidence}</span><span>p.{c.page}</span>
                    <button className="ml-auto inline-flex items-center gap-1 rounded border border-ink-200 px-1.5 py-0.5 text-ink-700 hover:bg-ink-50"
                      onClick={() => onView({ docId: c.doc_id, page: c.page, quote: c.quote })}><FileText className="h-3 w-3" />Source</button>
                  </div>
                </li>))}</ul></div>}
            {d.mentions_by_document?.length > 0 && <div><Sub>Mentioned in {d.mentions_by_document.length} document(s)</Sub>
              <ul className="space-y-0.5 text-[12px] text-ink-600">{d.mentions_by_document.slice(0, 12).map((m: any) => (
                <li key={m.doc_id} className="flex justify-between gap-2"><Link className="truncate hover:underline" to={`/documents/${m.doc_id}`}>{m.filename}</Link><span className="shrink-0 tabular-nums text-ink-400">{m.mentions}×</span></li>))}</ul></div>}
            {d.resolution_reviews?.length > 0 && <div><Sub>Entity-resolution reviews</Sub>{d.resolution_reviews.map((r: any) => <div key={r.id} className="text-[12px] text-ink-600">“{r.surface}” ~ {r.candidate_name} ({r.score}) — <b>{r.status}</b></div>)}</div>}
          </>
        )}
      </div>
    </div>
  );
}

export function EdgeDetail({ edge, nodes, onClose, onView }: { edge: GEdge; nodes: Map<string, GNode>; onClose: () => void; onView: (s: SourceRef) => void }) {
  const q = useQuery({ queryKey: ["edge", edge.id], queryFn: () => api.get(`/api/evidence/edge/${enc(edge.id)}`) });
  const p = edge.props || {};
  const s = nodes.get(edge.source), t = nodes.get(edge.target);
  const kind = edge.category !== "clinical" ? (edge.category === "terminology" ? "Reference terminology (not protocol evidence)" : edge.category === "mention" ? "Mention only (no clinical meaning)" : "Document structure")
    : edge.assertion_type === "normalized" ? "Normalised / inferred from a validated statement" : edge.assertion_type === "background_statement" ? "Background / literature statement" : "Directly extracted from protocol text";
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between gap-2 border-b border-ink-100 px-4 py-3">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Relationship</div>
          <h3 className="mt-1 text-[14px] font-semibold text-ink-900">{s?.name?.slice(0, 60) || edge.source} <span className="text-ink-400">—{prettyRel(edge.type)}→</span> {t?.name?.slice(0, 60) || edge.target}</h3>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-3 text-[13px]">
        <div className="flex flex-wrap gap-1.5"><Badge tone={edge.category === "clinical" ? "green" : "slate"}>{kind}</Badge><SupportBadge level={edge.support_level} />
          {p.validation_status && <Badge tone={p.validation_status === "validated" ? "green" : "amber"}>{p.validation_status}</Badge>}
          {edge.validation_check && edge.validation_check !== "ok" && <Badge tone="red">retrieval check: {edge.validation_check}</Badge>}</div>
        <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-[12px]">
          {[["Document", q.data?.document?.filename], ["Title", q.data?.document?.title], ["NCT", q.data?.document?.nct_id], ["Version", p.source_version_id], ["Pages", p.evidence_pages?.join(", ") || p.source_page_start],
            ["Section", p.source_section], ["Method", p.extraction_method], ["Confidence", p.extraction_confidence], ["Evidence count", p.evidence_count], ["Claim id", p.claim_id],
            ["Mentions", p.count], ["Basis", p.basis]].filter(([, v]) => v != null && v !== "").map(([k, v]) => (
            <><dt key={String(k) + "t"} className="text-ink-400">{k}</dt><dd key={String(k) + "d"} className="break-words text-ink-700">{String(v)}</dd></>))}
          {Object.entries(p).filter(([k]) => k.startsWith("q_")).map(([k, v]) => <><dt key={k + "t"} className="text-ink-400">{k.slice(2)}</dt><dd key={k + "d"}>{String(v)}</dd></>)}
        </dl>
        {q.isLoading && <Spinner label="Loading evidence" />}
        {q.data?.evidence?.length > 0 && <div><Sub>Supporting passages ({q.data.evidence.length})</Sub>
          <div className="space-y-2">{q.data.evidence.map((e: any) => (
            <div key={e.chunk_id} className="rounded border border-ink-200 px-2.5 py-2">
              <blockquote className="border-l-2 border-amber-300 pl-2 text-[12.5px] leading-relaxed text-ink-700">“{e.quote}”</blockquote>
              <div className="mt-1.5 flex items-center gap-2 text-[11px] text-ink-500"><span>p.{e.page_start}{e.page_end !== e.page_start ? `–${e.page_end}` : ""}</span><span className="truncate">{e.section}</span>
                <button className="ml-auto inline-flex items-center gap-1 rounded border border-ink-200 px-1.5 py-0.5 text-ink-700 hover:bg-ink-50"
                  onClick={() => onView({ docId: e.doc_id, page: e.page_start, chunkId: e.chunk_id, quote: e.quote, title: q.data?.document?.title })}><FileText className="h-3 w-3" />View source</button></div>
            </div>))}</div></div>}
        {edge.category === "clinical" && !q.isLoading && !q.data?.evidence?.length && p.supporting_quote && (
          <div><Sub>Supporting quote</Sub><blockquote className="border-l-2 border-amber-300 pl-2 text-[12.5px] text-ink-700">“{p.supporting_quote}”</blockquote></div>)}
        {edge.category === "mention" && p.pages && <div className="text-[12px] text-ink-600">Mentioned {p.count}× on pages {p.pages.join(", ")} as: {p.surface_forms?.join(", ")}</div>}
      </div>
    </div>
  );
}

function Sub({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-400">{children}</div>;
}
