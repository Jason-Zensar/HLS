// Small Markdown renderer for AI answers: headings, bullets, numbered lists, bold, and clickable citation chips.
//   [S3]  = source cited by the model         [~S3] = source matched automatically to an uncited sentence
import clsx from "clsx";
import type { ReactNode } from "react";

export function Md({ text, onCite, active }: { text: string; onCite?: (id: string) => void; active?: string | null }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: ReactNode[] } | null = null;
  const flush = () => {
    if (!list) return;
    out.push(list.ordered
      ? <ol key={out.length} className="ml-5 list-decimal space-y-1">{list.items.map((x, i) => <li key={i}>{x}</li>)}</ol>
      : <ul key={out.length} className="ml-1 space-y-1">{list.items.map((x, i) => <li key={i} className="flex gap-2"><span className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-ink-400" /><div className="min-w-0">{x}</div></li>)}</ul>);
    list = null;
  };
  lines.forEach((raw, i) => {
    const l = raw.trimEnd();
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    const b = l.match(/^\s*[-*•]\s+(.*)$/);
    const n = l.match(/^\s*\d+[.)]\s+(.*)$/);
    if (h) { flush(); out.push(<h4 key={i} className={clsx("font-semibold text-ink-900", h[1].length <= 2 ? "mt-4 text-[15px]" : "mt-3 text-[14px]")}>{inline(h[2], onCite, active)}</h4>); return; }
    if (b || n) {
      const ordered = !!n && !b;
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push(inline((b || n)![1], onCite, active));
      return;
    }
    flush();
    if (l.trim()) out.push(<p key={i}>{inline(l, onCite, active)}</p>);
  });
  flush();
  return <div className="space-y-2 text-[14px] leading-relaxed text-ink-700">{out}</div>;
}

function inline(s: string, onCite?: (id: string) => void, active?: string | null): ReactNode[] {
  const parts = s.split(/(\*\*[^*]+\*\*|\[~?S\d+(?:\s*[,;]\s*S\d+)*\])/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-semibold text-ink-900">{p.slice(2, -2)}</strong>;
    const m = p.match(/^\[(~?)(S\d+(?:\s*[,;]\s*S\d+)*)\]$/);
    if (m) {
      const auto = m[1] === "~";
      return <span key={i} className="whitespace-nowrap">{m[2].split(/\s*[,;]\s*/).map((id) => (
        <button key={id} onClick={() => onCite?.(id)} title={auto ? `Matched automatically to source ${id}` : `Cited source ${id}`}
          className={clsx("mx-0.5 inline-flex items-center rounded px-1 align-[1px] text-[10.5px] font-semibold leading-4 transition",
            auto ? "border border-dashed border-ink-300 text-ink-500 hover:border-ink-500" : "bg-blue-100 text-blue-800 hover:bg-blue-200",
            active === id && "ring-2 ring-blue-500")}>{auto ? "~" : ""}{id}</button>))}</span>;
    }
    return <span key={i}>{p}</span>;
  });
}
