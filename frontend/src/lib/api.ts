// Typed API client for the CTPIP backend.
export type Group = "trial" | "intervention" | "condition" | "biomarker" | "criterion" | "outcome" | "safety" | "evidence" | "other";

export interface GNode {
  id: string;
  element_id?: string;
  type: string;
  labels: string[];
  name: string;
  group: Group;
  props: Record<string, any>;
  scope?: string;
  degree?: number;
}

export interface GEdge {
  id: string;
  type: string;
  source: string;
  target: string;
  category: "clinical" | "structural" | "terminology" | "mention" | "other";
  assertion_type?: string;
  validation_status?: string;
  validation_check?: string;
  support_level?: string;
  confidence?: number;
  multiplicity?: number;
  props: Record<string, any>;
}

export interface PathRel { edge_id: string; type: string; direction: "forward" | "reverse" }
export interface GPath { start: string; end: string; nodes: string[]; relationships: PathRel[]; hops: number; score?: number; source: string }

export interface TreeNode { id: string; depth: number; via: { edge_id: string; type: string; direction: string } | null; is_answer: boolean; virtual?: boolean; children: TreeNode[] }
export interface TraversalStep { step: number; node: string; depth: number; parent: string | null; edge?: string | null; frontier: string[]; structure: "queue" | "stack" }
export interface Traversal { strategy: string; roots: string[]; virtual_root: boolean; order: TraversalStep[]; tree: TreeNode; reasoning_paths: GPath[]; unreached: string[] }

export interface EvidencePassage {
  edge_id: string; claim_id: string; relationship: string; subject: string; object: string; subject_id: string; object_id: string;
  doc_id: string; document_title?: string; filename?: string; nct_id?: string; version?: string; amendment?: string;
  page_start: number; page_end: number; section?: string; chunk_id: string; quote: string; support_level?: string;
  validation_status?: string; assertion_type?: string; confidence?: number;
}

export interface QueryResponse {
  query_id: string; question: string | null; interpreted_query: string; intent: string;
  matched_entities: { id: string; name: string; type: string; surface: string; method: string }[];
  retrieved_nodes: GNode[]; retrieved_relationships: GEdge[]; supporting_claims: any[]; supporting_documents: any[];
  evidence_passages: EvidencePassage[]; graph_paths: GPath[]; traversal: Traversal | null; retrieval_method: any;
  relevance_scores: Record<string, number>; validation_status: string; validation_issues: string[]; conflicts: any[];
  unresolved_terms: string[]; warnings: string[]; lexical_passages: any[];
  answer_summary: { status: string; text: string; items: any[]; generator: string; statement_types: Record<string, number>; disclaimer: string; llm_text?: string };
  latency_ms: number;
}

const TOKEN_KEY = "ctpip.token";
function headers(extra: Record<string, string> = {}): Record<string, string> {
  let t = "";
  try { t = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* storage unavailable */ }
  return t ? { ...extra, "X-API-Token": t } : extra;
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T = any>(url: string) => fetch(url, { headers: headers() }).then((r) => handle<T>(r)),
  post: <T = any>(url: string, body?: unknown) =>
    fetch(url, { method: "POST", headers: headers({ "Content-Type": "application/json" }), body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => handle<T>(r)),
  put: <T = any>(url: string, body?: unknown) =>
    fetch(url, { method: "PUT", headers: headers({ "Content-Type": "application/json" }), body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => handle<T>(r)),
  del: <T = any>(url: string) => fetch(url, { method: "DELETE", headers: headers() }).then((r) => handle<T>(r)),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch("/api/documents", { method: "POST", body: fd, headers: headers() }).then((r) => handle<any[]>(r));
  },
};

export const enc = encodeURIComponent;
export const pageImageUrl = (docId: string, page: number, chunkId?: string) =>
  `/api/documents/${docId}/pages/${page}/image${chunkId ? `?chunk_id=${enc(chunkId)}` : ""}`;
export const pdfUrl = (docId: string, page?: number) => `/api/documents/${docId}/file${page ? `#page=${page}` : ""}`;
