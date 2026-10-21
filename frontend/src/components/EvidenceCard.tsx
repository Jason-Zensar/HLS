import { FileText } from "lucide-react";
import type { EvidencePassage } from "../lib/api";
import { prettyRel } from "../lib/graphStyle";
import type { SourceRef } from "./SourceViewer";
import { Badge, SupportBadge } from "./ui";

export default function EvidenceCard({ p, onView, onFocus, active }: { p: EvidencePassage; onView: (s: SourceRef) => void; onFocus?: (edgeId: string) => void; active?: boolean }) {
  return (
    <div className={`rounded-md border px-3 py-2.5 transition ${active ? "border-blue-300 bg-blue-50/40" : "border-ink-200 bg-white hover:border-ink-300"}`}>
      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
        <button className="font-medium text-ink-800 hover:underline" onClick={() => onFocus?.(p.edge_id)} title="Highlight this relationship in the graph">
          {p.subject} <span className="text-ink-400">—{prettyRel(p.relationship)}→</span> {p.object}
        </button>
      </div>
      <blockquote className="mt-1.5 border-l-2 border-amber-300 pl-2 text-[12.5px] leading-relaxed text-ink-700">“{p.quote}”</blockquote>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-500">
        <SupportBadge level={p.support_level} />
        {p.validation_status && p.validation_status !== "validated" && <Badge tone="red">{p.validation_status}</Badge>}
        {p.nct_id && <Badge tone="blue">{p.nct_id}</Badge>}
        {p.version && <Badge>v {p.version}</Badge>}
        <span className="truncate" title={p.document_title}>{p.filename}</span>
        <span>· p.{p.page_start}{p.page_end !== p.page_start ? `–${p.page_end}` : ""}</span>
        {p.section && <span className="truncate" title={p.section}>· {p.section.slice(0, 40)}</span>}
        <button onClick={() => onView({ docId: p.doc_id, page: p.page_start, chunkId: p.chunk_id, quote: p.quote, title: p.document_title })}
          className="ml-auto inline-flex items-center gap-1 rounded border border-ink-200 px-1.5 py-0.5 font-medium text-ink-700 hover:bg-ink-50">
          <FileText className="h-3 w-3" /> View source
        </button>
      </div>
    </div>
  );
}
