import { GROUP_COLOR, GROUP_LABEL } from "../lib/graphStyle";
import type { Group } from "../lib/api";

const EDGE_KINDS = [
  { label: "Protocol evidence", dash: "", color: "#7c8597" },
  { label: "Normalised / inferred", dash: "5 3", color: "#7c8597" },
  { label: "Background literature", dash: "2 3", color: "#cbd5e1" },
  { label: "Reference terminology", dash: "6 3 1.5 3", color: "#a78bfa" },
  { label: "Document structure", dash: "1.5 3", color: "#94a3b8" },
  { label: "Mention only", dash: "4 4", color: "#cbd5e1" },
  { label: "Answer path", dash: "", color: "#f59e0b" },
];

export default function Legend({ hidden, onToggle, compact }: { hidden?: Set<Group>; onToggle?: (g: Group) => void; compact?: boolean }) {
  const groups = Object.keys(GROUP_LABEL).filter((g) => g !== "other") as Group[];
  return (
    <div className="space-y-3 text-xs">
      <div className="space-y-1">
        {groups.map((g) => (
          <button key={g} type="button" onClick={() => onToggle?.(g)} disabled={!onToggle}
            className={`flex w-full items-center gap-2 rounded px-1 py-0.5 text-left ${onToggle ? "hover:bg-ink-50" : ""} ${hidden?.has(g) ? "opacity-35" : ""}`}
            title={onToggle ? "Show / hide category" : undefined}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: GROUP_COLOR[g] }} />
            <span className="text-ink-600">{GROUP_LABEL[g]}</span>
          </button>
        ))}
      </div>
      {!compact && (
        <div className="space-y-1 border-t border-ink-100 pt-2">
          {EDGE_KINDS.map((k) => (
            <div key={k.label} className="flex items-center gap-2 px-1">
              <svg width="26" height="8"><line x1="1" y1="4" x2="25" y2="4" stroke={k.color} strokeWidth={k.label === "Answer path" ? 3 : 1.6} strokeDasharray={k.dash} /></svg>
              <span className="text-ink-600">{k.label}</span>
            </div>
          ))}
          <div className="flex items-center gap-2 px-1"><svg width="26" height="12"><circle cx="13" cy="6" r="4.5" fill="#fff" stroke="#6b7280" strokeDasharray="2 1.5" /></svg><span className="text-ink-600">Protocol-specific node</span></div>
          <div className="flex items-center gap-2 px-1"><svg width="26" height="12"><circle cx="13" cy="6" r="4.5" fill="#7c3aed" stroke="#f59e0b" strokeWidth="2" /></svg><span className="text-ink-600">Unresolved / ambiguous entity</span></div>
        </div>
      )}
    </div>
  );
}
