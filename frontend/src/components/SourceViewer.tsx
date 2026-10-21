import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, enc, pageImageUrl, pdfUrl } from "../lib/api";
import { Badge, Button, Spinner } from "./ui";

export interface SourceRef { docId: string; page: number; chunkId?: string; quote?: string; title?: string }

export default function SourceViewer({ source, onClose }: { source: SourceRef | null; onClose: () => void }) {
  const [page, setPage] = useState(source?.page ?? 1);
  useEffect(() => setPage(source?.page ?? 1), [source]);
  const chunk = useQuery({
    queryKey: ["chunk", source?.chunkId],
    queryFn: () => api.get(`/api/evidence/chunk/${enc(source!.chunkId!)}`),
    enabled: !!source?.chunkId,
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  if (!source) return null;
  const doc = chunk.data?.document;
  const total = doc?.page_count ?? 9999;
  const onChunkPage = page >= (chunk.data?.chunk?.page_start ?? source.page) && page <= (chunk.data?.chunk?.page_end ?? source.page);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/50 p-4" onClick={onClose}>
      <div className="flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between gap-3 border-b border-ink-100 px-4 py-2.5">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ink-800">{doc?.title || source.title || source.docId}</div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
              <span>{doc?.filename}</span>
              {doc?.nct_id && <Badge tone="blue">{doc.nct_id}</Badge>}
              {(doc?.version_label || doc?.version_date) && <Badge>version {doc.version_label || doc.version_date}</Badge>}
              {doc?.amendment && <Badge>amendment {doc.amendment}</Badge>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft className="h-3.5 w-3.5" /></Button>
            <span className="text-xs tabular-nums text-ink-600">page {page}{doc ? ` / ${doc.page_count}` : ""}</span>
            <Button size="sm" onClick={() => setPage((p) => Math.min(total, p + 1))}><ChevronRight className="h-3.5 w-3.5" /></Button>
            <a className="inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-700 hover:bg-ink-50" href={pdfUrl(source.docId, page)} target="_blank" rel="noreferrer">
              <ExternalLink className="h-3.5 w-3.5" /> Open PDF at page
            </a>
            <Button size="sm" variant="ghost" onClick={onClose} title="Close (Esc)"><X className="h-4 w-4" /></Button>
          </div>
        </header>
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_380px]">
          <div className="min-h-0 overflow-auto bg-ink-100 p-4">
            <img key={`${source.docId}-${page}`} src={pageImageUrl(source.docId, page, onChunkPage ? source.chunkId : undefined)} alt={`Page ${page}`}
              className="mx-auto max-w-full rounded bg-white shadow" />
            {onChunkPage && source.chunkId && <p className="mt-2 text-center text-[11px] text-ink-500">Highlighted region = the extracted passage's bounding box on this page (from the PDF text layer).</p>}
          </div>
          <aside className="min-h-0 space-y-3 overflow-auto border-l border-ink-100 p-4 text-sm">
            {source.quote && (
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Supporting quote</div>
                <blockquote className="rounded-md border-l-[3px] border-amber-400 bg-amber-50/60 px-3 py-2 text-[13px] leading-relaxed text-ink-800">{source.quote}</blockquote>
              </div>
            )}
            {chunk.isLoading && <Spinner label="Loading passage context" />}
            {chunk.data && (
              <>
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Section</div>
                  <div className="text-[13px] text-ink-700">{chunk.data.section ? `${chunk.data.section.number || ""} ${chunk.data.section.title || ""}` : "—"}
                    {chunk.data.section && <span className="ml-1 text-ink-400">({chunk.data.section.category})</span>}</div>
                  <div className="mt-1 text-xs text-ink-500">pages {chunk.data.chunk.page_start}–{chunk.data.chunk.page_end} · {chunk.data.chunk.chunk_type} · {chunk.data.chunk.extraction_method} · confidence {chunk.data.chunk.extraction_confidence}</div>
                </div>
                {chunk.data.table && (
                  <div>
                    <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Source table {chunk.data.table.title ? `· ${chunk.data.table.title}` : ""}</div>
                    <div className="max-h-56 overflow-auto rounded border border-ink-200">
                      <table className="w-full text-[11px]"><tbody>
                        {chunk.data.table.cells.slice(0, 30).map((r: string[], i: number) => (
                          <tr key={i} className={i === 0 ? "bg-ink-50 font-medium" : ""}>{r.map((c, j) => <td key={j} className="border-b border-r border-ink-100 px-1.5 py-1 align-top">{c}</td>)}</tr>
                        ))}
                      </tbody></table>
                    </div>
                  </div>
                )}
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Surrounding section context</div>
                  <div className="space-y-2">
                    {chunk.data.context.map((c: any) => (
                      <p key={c.id} className={`whitespace-pre-wrap rounded px-2 py-1.5 text-[12px] leading-relaxed ${c.id === source.chunkId ? "bg-amber-50 ring-1 ring-amber-200" : "text-ink-600"}`}>
                        <span className="mr-1 text-[10px] text-ink-400">p.{c.page_start}</span>{c.text.slice(0, 900)}{c.text.length > 900 ? " …" : ""}
                      </p>
                    ))}
                  </div>
                </div>
              </>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
