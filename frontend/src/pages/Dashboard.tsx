import { useQuery } from "@tanstack/react-query";
import { BookOpen, Bot, Columns3, FileStack, Search, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "../App";
import { Card, Empty, ErrorBox, Spinner, fmtTime } from "../components/ui";
import { api } from "../lib/api";
import { useAiStatus } from "../lib/ai";
import { QualityPanel } from "./Quality";

export default function Dashboard() {
  const q = useQuery({ queryKey: ["stats"], queryFn: () => api.get("/api/stats"), refetchInterval: 15_000 });
  const ai = useAiStatus();
  const d = q.data;
  const g = d?.graph;
  const n = (v: any) => (v == null ? "-" : Number(v).toLocaleString());
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Dashboard" subtitle="Breast-cancer clinical trial protocols, read and organised so anyone can study them." />
      <div className="flex-1 space-y-5 overflow-auto p-6">
        {q.isLoading && <Spinner label="Loading" />}
        <ErrorBox error={q.error} />
        {d && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Tile icon={FileStack} label="Protocols ready" value={`${n(d.documents.processed)} / ${n(d.documents.total)}`}
                sub={d.documents.pending ? `${n(d.documents.pending)} still being read` : `${n(d.documents.pages)} pages read`} />
              <Tile icon={BookOpen} label="Facts found" value={n(g?.clinical)} sub={g?.clinical ? `${Math.round((100 * g.validated) / g.clinical)}% checked against the text` : "graph offline"} />
              <Tile icon={Search} label="Drugs, tests & outcomes" value={n(g ? g.drugs + g.interventions + g.biomarkers + g.endpoints : null)} sub={g ? `${n(g.drugs)} drugs · ${n(g.endpoints)} outcomes` : ""} />
              <Tile icon={Bot} label="Local AI" value={ai.data?.ready ? "Ready" : ai.data && !ai.data.enabled ? "Off" : "Not ready"}
                sub={ai.data?.ready ? ai.data.settings.model : <Link to="/settings" className="text-violet-700 hover:underline">Set up in Settings</Link>} tone={ai.data?.ready ? "text-emerald-700" : "text-amber-700"} />
            </div>

            <div>
              <h2 className="mb-2 text-[13px] font-semibold text-ink-700">What would you like to do?</h2>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                <Action to="/documents" icon={BookOpen} title="Study a protocol" text="Open any protocol for a plain-language overview, an AI explanation and Q&A." />
                <Action to="/assistant" icon={Sparkles} title="Ask AI" text="Ask questions about one or all protocols. Answers show their sources." />
                <Action to="/search" icon={Search} title="Search" text="Find trials by drug, disease, biomarker or outcome, or search the exact wording." />
                <Action to="/compare" icon={Columns3} title="Compare protocols" text="Put 2 to 4 protocols side by side and see what differs." />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title="Recent questions">
                {d.recent_queries.length === 0 ? <Empty>No questions yet</Empty> : (
                  <ul className="divide-y divide-ink-100 text-[13px]">{d.recent_queries.slice(0, 6).map((r: any) => (
                    <li key={r.id} className="py-1.5"><Link to={`/search?tab=graph&q=${encodeURIComponent(r.question)}`} className="block truncate text-ink-700 hover:underline">{r.question}</Link></li>))}</ul>)}
              </Card>
              <Card title="Recent activity">
                <ul className="divide-y divide-ink-100 text-[12.5px]">{d.recent_activity.slice(0, 6).map((a: any, i: number) => (
                  <li key={i} className="flex gap-2 py-1.5"><span className="w-36 shrink-0 text-ink-400">{fmtTime(a.ts)}</span><span className="min-w-0 truncate text-ink-700">{a.message}</span></li>))}</ul>
              </Card>
            </div>

            <div id="quality">
              <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-ink-700"><ShieldCheck className="h-4 w-4 text-emerald-600" />Data quality
                <span className="font-normal text-ink-400">- reading warnings ({n(d.warnings.warnings)}), errors ({n(d.warnings.errors)}), drug names awaiting review and differences between sources</span></h2>
              <QualityPanel />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Tile({ icon: Icon, label, value, sub, tone }: { icon: any; label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-ink-200 bg-white px-4 py-3">
      <div className="rounded-md bg-violet-50 p-2 text-violet-700"><Icon className="h-5 w-5" /></div>
      <div className="min-w-0"><div className="text-[12px] font-medium text-ink-500">{label}</div>
        <div className={`text-[22px] font-semibold tabular-nums ${tone || "text-ink-900"}`}>{value}</div>
        {sub && <div className="truncate text-[12px] text-ink-500">{sub}</div>}</div>
    </div>
  );
}

function Action({ to, icon: Icon, title, text }: { to: string; icon: any; title: string; text: string }) {
  return (
    <Link to={to} className="group rounded-lg border border-ink-200 bg-white p-4 transition hover:border-violet-300 hover:shadow-sm">
      <div className="flex items-center gap-2 text-[14px] font-semibold text-ink-900"><Icon className="h-4 w-4 text-violet-600" />{title}</div>
      <p className="mt-1 text-[12.5px] leading-snug text-ink-500">{text}</p>
      <span className="mt-2 inline-block text-[12px] font-medium text-violet-700 group-hover:underline">Open</span>
    </Link>
  );
}

export function Bars({ rows, color = "#2563eb" }: { rows: { label: string; value: number }[]; color?: string }) {
  if (!rows.length) return <Empty>No data</Empty>;
  const max = Math.max(...rows.map((r) => r.value));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[150px_1fr_56px] items-center gap-2 text-[12px]">
          <span className="truncate text-ink-600" title={r.label}>{r.label}</span>
          <div className="h-2 rounded bg-ink-100"><div className="h-2 rounded" style={{ width: `${(100 * r.value) / max}%`, background: color }} /></div>
          <span className="text-right tabular-nums text-ink-500">{r.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
