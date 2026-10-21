import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { SUPPORT_LABEL, SUPPORT_TONE } from "../lib/graphStyle";

export function Card({ title, actions, children, className, bodyClass }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={clsx("rounded-lg border border-ink-200 bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)]", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-ink-100 px-4 py-2.5">
          <h3 className="text-[13px] font-semibold text-ink-700">{title}</h3>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={clsx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function Button({ children, onClick, variant = "default", size = "md", disabled, title, className, type = "button" }: {
  children: ReactNode; onClick?: () => void; variant?: "default" | "primary" | "ghost" | "danger"; size?: "sm" | "md"; disabled?: boolean; title?: string; className?: string; type?: "button" | "submit";
}) {
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={clsx("inline-flex items-center gap-1.5 rounded-md font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-[13px]",
        variant === "primary" && "bg-ink-900 text-white hover:bg-ink-700",
        variant === "default" && "border border-ink-200 bg-white text-ink-700 hover:bg-ink-50",
        variant === "ghost" && "text-ink-600 hover:bg-ink-100",
        variant === "danger" && "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50", className)}>
      {children}
    </button>
  );
}

export function Badge({ children, tone = "slate", className, title }: { children: ReactNode; tone?: "slate" | "green" | "blue" | "amber" | "red" | "violet"; className?: string; title?: string }) {
  const t = {
    slate: "bg-ink-100 text-ink-600 ring-ink-200", green: "bg-emerald-50 text-emerald-700 ring-emerald-200", blue: "bg-blue-50 text-blue-700 ring-blue-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200", red: "bg-rose-50 text-rose-700 ring-rose-200", violet: "bg-violet-50 text-violet-700 ring-violet-200",
  }[tone];
  return <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", t, className)}>{children}</span>;
}

export function SupportBadge({ level }: { level?: string }) {
  if (!level) return null;
  return <span className={clsx("inline-flex whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", SUPPORT_TONE[level] || SUPPORT_TONE.uncertain)}>{SUPPORT_LABEL[level] || level}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ({ ready: "green", processed: "green", queued: "slate", processing: "blue", failed: "red", verified: "green", verified_with_warnings: "amber", no_results: "slate", done: "green", running: "blue" } as any)[status] || "slate";
  return <Badge tone={tone}>{status.replace(/_/g, " ")}</Badge>;
}

export function Spinner({ label }: { label?: string }) {
  return <div className="flex items-center gap-2 text-sm text-ink-500"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-ink-200 px-4 py-8 text-center text-sm text-ink-400">{children}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{(error as Error).message || String(error)}</div>;
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-ink-200 bg-white px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-ink-400">{label}</div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", tone || "text-ink-800")}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-500">{sub}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { id: T; label: ReactNode }[] }) {
  return (
    <div className="flex gap-1 rounded-md bg-ink-100 p-0.5">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={clsx("rounded px-2.5 py-1 text-xs font-medium transition", value === t.id ? "bg-white text-ink-800 shadow-sm" : "text-ink-500 hover:text-ink-700")}>{t.label}</button>
      ))}
    </div>
  );
}

export function fmtTime(ts?: number | null) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export function Markdownish({ text }: { text: string }) {
  // tiny renderer: **bold**, bullet lines
  const lines = text.split("\n");
  return (
    <div className="space-y-1 text-[13px] leading-relaxed text-ink-700">
      {lines.map((l, i) => {
        const bullet = l.startsWith("- ");
        const body = (bullet ? l.slice(2) : l).split(/(\*\*[^*]+\*\*)/g).map((p, j) => p.startsWith("**") ? <strong key={j} className="font-semibold text-ink-900">{p.slice(2, -2)}</strong> : <span key={j}>{p}</span>);
        return bullet ? <div key={i} className="flex gap-2 pl-1"><span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-400" /><div>{body}</div></div> : <p key={i}>{body}</p>;
      })}
    </div>
  );
}
