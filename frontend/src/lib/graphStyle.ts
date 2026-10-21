import type { GEdge, GNode, Group } from "./api";

export const GROUP_COLOR: Record<Group, string> = {
  trial: "#2563eb",
  intervention: "#7c3aed",
  condition: "#0d9488",
  biomarker: "#d97706",
  criterion: "#6b7280",
  outcome: "#16a34a",
  safety: "#be4b49",
  evidence: "#475569",
  other: "#94a3b8",
};

export const GROUP_LABEL: Record<Group, string> = {
  trial: "Trials & protocols",
  intervention: "Drugs & interventions",
  condition: "Diseases, subtypes & settings",
  biomarker: "Biomarkers & targets",
  criterion: "Eligibility criteria",
  outcome: "Endpoints & assessments",
  safety: "Adverse events & safety",
  evidence: "Documents & evidence",
  other: "Other",
};

export const nodeColor = (n: Pick<GNode, "group">) => GROUP_COLOR[n.group] || GROUP_COLOR.other;

export function nodeRadius(n: GNode): number {
  if (n.type === "Protocol") return 9;
  if (n.type === "ClinicalTrial") return 8;
  const d = n.degree ?? 0;
  return Math.max(5, Math.min(16, 5 + Math.sqrt(d) * 1.4));
}

// Edge styling: clinical = solid, structural = dotted, terminology = dash-dot, mention = light dashed
export function edgeDash(e: Pick<GEdge, "category" | "assertion_type">): string | null {
  if (e.assertion_type === "background_statement") return "2 3";
  switch (e.category) {
    case "structural": return "1.5 3";
    case "terminology": return "6 3 1.5 3";
    case "mention": return "4 4";
    default: return e.assertion_type === "normalized" ? "5 3" : null;
  }
}

export function edgeColor(e: Pick<GEdge, "category" | "validation_check" | "assertion_type">): string {
  if (e.validation_check && !["ok", "low_confidence"].includes(e.validation_check)) return "#dc2626";
  if (e.category === "mention") return "#cbd5e1";
  if (e.category === "terminology") return "#a78bfa";
  if (e.category === "structural") return "#94a3b8";
  if (e.assertion_type === "background_statement") return "#cbd5e1";
  return "#7c8597";
}

export const SUPPORT_LABEL: Record<string, string> = {
  supported_by_multiple_passages: "Multiple passages",
  supported_by_one_passage: "One passage",
  inferred_from_validated_graph_path: "Inferred",
  background_literature: "Background literature",
  reference_terminology: "Reference terminology",
  mention_only: "Mention only",
  document_structure: "Document structure",
  uncertain: "Uncertain",
};

export const SUPPORT_TONE: Record<string, string> = {
  supported_by_multiple_passages: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  supported_by_one_passage: "bg-sky-50 text-sky-700 ring-sky-200",
  inferred_from_validated_graph_path: "bg-violet-50 text-violet-700 ring-violet-200",
  background_literature: "bg-amber-50 text-amber-700 ring-amber-200",
  reference_terminology: "bg-purple-50 text-purple-700 ring-purple-200",
  mention_only: "bg-slate-50 text-slate-600 ring-slate-200",
  document_structure: "bg-slate-50 text-slate-600 ring-slate-200",
  uncertain: "bg-rose-50 text-rose-700 ring-rose-200",
};

export function shortLabel(s: string, n = 28): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function prettyRel(t: string): string {
  return t.toLowerCase().replace(/_/g, " ");
}
