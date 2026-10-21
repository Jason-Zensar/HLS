import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FolderInput, RotateCw, Search, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../App";
import { Badge, Button, ErrorBox, Spinner, StatusBadge } from "../components/ui";
import { api } from "../lib/api";

export default function Documents() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [drag, setDrag] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const [technical, setTechnical] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const docs = useQuery({ queryKey: ["docs", q, status], queryFn: () => api.get(`/api/documents?q=${encodeURIComponent(q)}&status=${status}&limit=1000`), refetchInterval: 5000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["docs"] });
  const upload = useMutation({
    mutationFn: (files: File[]) => api.upload(files),
    onSuccess: (r) => { const c = (s: string) => r.filter((x) => x.status === s).length; setMsg(`${c("queued")} added for processing · ${c("duplicate")} already in the library · ${c("rejected")} rejected${r.filter((x) => x.message && x.status === "rejected").map((x) => ` - ${x.filename}: ${x.message}`).join("")}`); refresh(); },
  });
  const importFolder = useMutation({ mutationFn: () => api.post("/api/documents/import-folder"), onSuccess: (r) => { setMsg(`Dataset folder: ${r.queued} added, ${r.duplicates} already in the library, ${r.rejected} rejected`); refresh(); } });
  const act = useMutation({
    mutationFn: ({ id, a }: { id: string; a: "retry" | "delete" }) => (a === "delete" ? api.del(`/api/documents/${id}`) : api.post(`/api/documents/${id}/${a}`)),
    onSuccess: refresh,
  });
  const onFiles = (fl: FileList | null) => { if (fl && fl.length) upload.mutate(Array.from(fl).filter((f) => f.name.toLowerCase().endsWith(".pdf"))); };
  const items = [...(docs.data?.items || [])].sort((a: any, b: any) => a.filename.localeCompare(b.filename, undefined, { numeric: true }));
  const busy = items.filter((d: any) => d.status === "queued" || d.status === "processing").length;
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Protocols" subtitle={`${docs.data?.total ?? "..."} clinical trial protocols. Click "Study" to read a plain-language overview, an AI explanation, or ask questions.`}
        actions={<Button onClick={() => importFolder.mutate()} disabled={importFolder.isPending} title="Add every PDF from the dataset folders"><FolderInput className="h-3.5 w-3.5" />Load dataset folder</Button>} />
      <div className="flex-1 space-y-3 overflow-auto p-6">
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}
          className={`flex items-center justify-between rounded-lg border-2 border-dashed px-5 py-3 ${drag ? "border-violet-400 bg-violet-50" : "border-ink-200 bg-white"}`}>
          <div className="text-[13px] text-ink-600"><b className="text-ink-800">Add protocols:</b> drop PDF files here or choose them. They are read automatically in the background.</div>
          <input ref={fileRef} type="file" accept="application/pdf" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          <Button variant="primary" onClick={() => fileRef.current?.click()} disabled={upload.isPending}><Upload className="h-3.5 w-3.5" />{upload.isPending ? "Uploading..." : "Choose PDFs"}</Button>
        </div>
        {msg && <div className="rounded-md border border-ink-200 bg-white px-3 py-2 text-[13px] text-ink-700">{msg}</div>}
        {busy > 0 && <div className="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-[13px] text-blue-800"><Spinner />{busy} protocol(s) are being read. You can keep working.</div>}
        <ErrorBox error={upload.error || importFolder.error || act.error} />
        <div className="flex items-center gap-2">
          <div className="relative w-96"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find by name, drug, trial number or sponsor..." className="w-full rounded-md border border-ink-200 py-1.5 pl-8 pr-2 text-[13px]" /></div>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-ink-200 bg-white px-2 py-1.5 text-[13px]">
            <option value="">All</option><option value="processed">Ready</option><option value="queued">Waiting</option><option value="processing">Being read</option><option value="failed">Failed</option>
          </select>
          <label className="ml-auto flex items-center gap-1.5 text-[12.5px] text-ink-500"><input type="checkbox" checked={technical} onChange={(e) => setTechnical(e.target.checked)} />Show technical columns</label>
        </div>
        <div className="overflow-auto rounded-lg border border-ink-200 bg-white">
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-ink-50 text-left text-[11px] uppercase tracking-wide text-ink-500">
              <tr>{["Protocol", "Phase", "Trial ID", "Pages", "Status", ...(technical ? ["Version", "Type", "Entities", "Facts", "Warnings"] : []), ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((d: any) => (
                <tr key={d.id} className="hover:bg-ink-50/60">
                  <td className="max-w-[560px] px-3 py-2"><Link to={`/documents/${d.id}`} className="font-medium text-ink-900 hover:underline">{d.filename.replace(/\.pdf$/i, "")}</Link>
                    <div className="truncate text-[11.5px] text-ink-400" title={d.title}>{d.sponsor ? `${d.sponsor} · ` : ""}{d.title}</div>
                    {d.error && <div className="truncate text-[11px] text-rose-600" title={d.error}>{d.error}</div>}</td>
                  <td className="whitespace-nowrap px-3 py-2">{d.phase || "-"}</td>
                  <td className="px-3 py-2">{d.nct_id ? <Badge tone="blue">{d.nct_id}</Badge> : <span className="text-ink-400">{d.sponsor_protocol_code || "-"}</span>}</td>
                  <td className="px-3 py-2 tabular-nums">{d.page_count}</td>
                  <td className="px-3 py-2"><StatusBadge status={d.status === "processed" ? "ready" : d.status} /></td>
                  {technical && <>
                    <td className="px-3 py-2 text-ink-600">{[d.version_label && `v${d.version_label}`, d.amendment && `am.${d.amendment}`, d.version_date].filter(Boolean).join(" · ") || "-"}</td>
                    <td className="px-3 py-2">{d.document_type || "-"}</td>
                    <td className="px-3 py-2 tabular-nums">{d.entity_count ?? 0}</td>
                    <td className="px-3 py-2 tabular-nums">{d.relationship_count ?? 0}</td>
                    <td className="px-3 py-2">{d.warning_count ? <Badge tone="amber">{d.warning_count}</Badge> : <span className="text-ink-300">0</span>}</td></>}
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {d.status === "processed" && <Link to={`/documents/${d.id}`} className="mr-1 inline-flex items-center gap-1 rounded-md bg-violet-600 px-2.5 py-1 text-[12px] font-medium text-white hover:bg-violet-700"><BookOpen className="h-3.5 w-3.5" />Study</Link>}
                    {d.status === "failed" && <Button size="sm" variant="ghost" title="Try again" onClick={() => act.mutate({ id: d.id, a: "retry" })}><RotateCw className="h-3.5 w-3.5" /></Button>}
                    <Button size="sm" variant="ghost" title="Remove this protocol" disabled={d.status === "processing"}
                      onClick={() => confirm(`Remove ${d.filename}? Its stored file, text and graph facts will be deleted.`) && act.mutate({ id: d.id, a: "delete" })}><Trash2 className="h-3.5 w-3.5 text-rose-600" /></Button>
                  </td>
                </tr>))}
            </tbody>
          </table>
          {!items.length && !docs.isLoading && <div className="p-6 text-center text-sm text-ink-400">No protocols yet. Add PDFs above or press "Load dataset folder".</div>}
        </div>
      </div>
    </div>
  );
}
