import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft, Download, Maximize2, Route as RouteIcon, Search, Settings2, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../App";
import { AiAnswer, AiToggle } from "../components/AiAnswer";
import { useAiToggle } from "../lib/ai";
import { EdgeDetail, NodeDetail } from "../components/DetailPanel";
import EvidenceCard from "../components/EvidenceCard";
import GraphCanvas, { type GraphCanvasHandle } from "../components/GraphCanvas";
import Legend from "../components/Legend";
import SourceViewer, { type SourceRef } from "../components/SourceViewer";
import TraversalPlayer from "../components/TraversalPlayer";
import TreeView, { type UTree } from "../components/TreeView";
import { Badge, Button, Card, Empty, ErrorBox, Markdownish, Spinner, StatusBadge, SupportBadge, Tabs } from "../components/ui";
import { api, enc, type GEdge, type GNode, type GPath, type QueryResponse } from "../lib/api";
import { prettyRel, shortLabel, SUPPORT_LABEL } from "../lib/graphStyle";
import { bfs, dfs, type Step } from "../lib/traverse";

const EXAMPLES = [
  "Which breast cancer trials investigate trastuzumab?",
  "Find protocols that combine pembrolizumab with chemotherapy",
  "Which trials use PIK3CA in eligibility criteria?",
  "Show the inclusion and exclusion criteria across trials investigating palbociclib",
  "Which protocols use different dosing schedules for paclitaxel?",
  "Which studies investigate triple-negative breast cancer?",
  "Find trials that share the same primary endpoint",
  "Which protocols describe neutropenia with abemaciclib?",
  "Find every protocol that mentions hot flashes and show its context",
  "Which studies use the same intervention but have different primary endpoints?",
  "Trace olaparib to its treatment arm, study population, endpoint and source protocol",
  "Show every source supporting or contradicting a claim about the dosing schedule of capecitabine",
  "Which trials investigate CDK4/6 inhibitors?",
  "What is the relationship between ribociclib and progression-free survival?",
];

type View = "tree" | "graph" | "paths" | "plan";

export default function QueryWorkspace({ embedded }: { embedded?: boolean } = {}) {
  const [params, setParams] = useSearchParams();
  const [aiOn, setAiOn] = useAiToggle("graph-query");
  const [question, setQuestion] = useState(params.get("q") || "");
  const [strategy, setStrategy] = useState<"bfs" | "dfs">("bfs");
  const [view, setView] = useState<View>("tree");
  const [structuredOpen, setStructuredOpen] = useState(false);
  const [sel, setSel] = useState<{ node?: GNode; edge?: GEdge } | null>(null);
  const [activePath, setActivePath] = useState<GPath | null>(null);
  const [source, setSource] = useState<SourceRef | null>(null);
  const [rootId, setRootId] = useState<string>("");
  const [stepIdx, setStepIdx] = useState<number>(-1);
  const graphRef = useRef<GraphCanvasHandle>(null);

  const run = useMutation({
    mutationFn: (body: { question?: string; structured?: any }) =>
      body.structured ? api.post<QueryResponse>("/api/query/structured", { ...body.structured, strategy })
        : api.post<QueryResponse>("/api/query", { question: body.question, strategy, limit: 25 }),
    onSuccess: (r) => { setSel(null); setActivePath(null); setRootId(""); setStepIdx(-1); if (r.question && !r.question.startsWith("[structured]")) setParams({ ...Object.fromEntries(params), q: r.question }); },
  });
  useEffect(() => { if (params.get("q")) run.mutate({ question: params.get("q")! }); /* eslint-disable-next-line */ }, []);

  const r = run.data;
  const nodeMap = useMemo(() => new Map((r?.retrieved_nodes || []).map((n) => [n.id, n])), [r]);
  const edgeMap = useMemo(() => new Map((r?.retrieved_relationships || []).map((e) => [e.id, e])), [r]);
  const answerNodes = useMemo(() => new Set((r?.answer_summary.items || []).map((i: any) => i.node_id).filter(Boolean)), [r]);

  // ---- traversal: server tree by default, client-side BFS/DFS when another root / strategy is chosen
  const serverRoot = r?.traversal?.roots?.[0] || "";
  const effectiveRoot = rootId || "";
  const steps: Step[] = useMemo(() => {
    if (!r?.traversal) return [];
    if (!effectiveRoot && r.traversal.strategy === strategy) return r.traversal.order.map((s) => ({ ...s, edge: s.edge ?? null }));
    const root = effectiveRoot || serverRoot;
    if (!root) return [];
    const ids = r.retrieved_nodes.map((n) => n.id);
    return strategy === "bfs" ? bfs(root, ids, r.retrieved_relationships) : dfs(root, ids, r.retrieved_relationships);
  }, [r, strategy, effectiveRoot, serverRoot]);

  const tree: UTree | null = useMemo(() => {
    if (!r?.traversal) return null;
    if (!effectiveRoot && r.traversal.strategy === strategy) return r.traversal.tree as UTree;
    const map = new Map<string, UTree>();
    steps.forEach((s) => {
      const e = s.edge ? edgeMap.get(s.edge) : undefined;
      map.set(s.node, { id: s.node, via: e ? { edge_id: e.id, type: e.type, direction: e.source === s.parent ? "out" : "in" } : null, is_answer: answerNodes.has(s.node), children: [] });
    });
    let root: UTree | null = null;
    steps.forEach((s) => { const t = map.get(s.node)!; if (s.parent && map.has(s.parent)) map.get(s.parent)!.children.push(t); else if (!root) root = t; });
    return root;
  }, [r, steps, strategy, effectiveRoot, edgeMap, answerNodes]);

  const visitOrder = useMemo(() => {
    const m = new Map<string, number>();
    if (stepIdx < 0) return m;
    steps.slice(0, stepIdx + 1).forEach((s, i) => m.set(s.node, i));
    return m;
  }, [steps, stepIdx]);
  const currentNode = stepIdx >= 0 ? steps[stepIdx]?.node : null;
  const onStep = useCallback((i: number) => setStepIdx(i), []);

  const pathEdges = useMemo(() => new Set(activePath?.relationships.map((x) => x.edge_id) || []), [activePath]);
  const pathNodes = useMemo(() => new Set(activePath?.nodes || []), [activePath]);

  const passages = useMemo(() => {
    const all = r?.evidence_passages || [];
    if (sel?.edge) return all.filter((p) => p.edge_id === sel.edge!.id);
    if (sel?.node) return all.filter((p) => p.subject_id === sel.node!.id || p.object_id === sel.node!.id);
    if (activePath) return all.filter((p) => pathEdges.has(p.edge_id));
    return all;
  }, [r, sel, activePath, pathEdges]);

  const allPaths = useMemo(() => {
    if (!r) return [] as (GPath & { label: string })[];
    const seen = new Set<string>();
    const out: (GPath & { label: string })[] = [];
    for (const p of [...(r.traversal?.reasoning_paths || []), ...r.graph_paths]) {
      const k = p.relationships.map((x) => x.edge_id).join(">");
      if (seen.has(k)) continue;
      seen.add(k);
      out.push({ ...p, label: p.source });
    }
    return out.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }, [r]);

  const submit = () => question.trim().length >= 3 && run.mutate({ question: question.trim() });

  return (
    <div className="flex h-full flex-col">
      {!embedded && <PageHeader title="Graph Query Workspace" subtitle="Natural-language questions are resolved to graph entities and executed as validated, read-only graph patterns (GraphRAG: BFS / DFS traversal + evidence retrieval)." />}
      <div className="border-b border-ink-200 bg-white px-6 py-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="Ask about drugs, biomarkers, subtypes, endpoints, eligibility, doses, adverse events, protocols…"
              className="w-full rounded-md border border-ink-200 bg-white py-2 pl-9 pr-3 text-[13.5px] outline-none ring-blue-500 focus:ring-2" />
          </div>
          <Tabs value={strategy} onChange={(v) => setStrategy(v)} tabs={[{ id: "bfs", label: "BFS" }, { id: "dfs", label: "DFS" }]} />
          <Button variant="primary" onClick={submit} disabled={run.isPending}><Sparkles className="h-3.5 w-3.5" />Run query</Button>
          <Button onClick={() => setStructuredOpen((o) => !o)} title="Structured query builder"><Settings2 className="h-3.5 w-3.5" />Structured</Button>
          <AiToggle on={aiOn} onChange={setAiOn} />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => { setQuestion(ex); run.mutate({ question: ex }); }}
              className="rounded-full border border-ink-200 bg-ink-50 px-2.5 py-0.5 text-[11.5px] text-ink-600 hover:border-ink-300 hover:bg-white">{shortLabel(ex, 64)}</button>
          ))}
        </div>
        {structuredOpen && <StructuredBuilder onRun={(s) => run.mutate({ structured: s })} />}
      </div>

      {run.isPending && <div className="p-6"><Spinner label="Resolving entities, planning graph patterns, traversing and validating…" /></div>}
      {run.error && <div className="p-6"><ErrorBox error={run.error} /></div>}
      {!r && !run.isPending && !run.error && (
        <div className="p-6"><Empty>Run a question or pick an example. Results show the retrieved subgraph as an answer tree (BFS / DFS), the multi-hop reasoning paths, and the exact source passages.</Empty></div>
      )}

      {r && !run.isPending && (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 bg-white px-6 py-2 text-[12px]">
            <Badge tone="violet">{r.intent.replace(/_/g, " ")}</Badge>
            <span className="text-ink-700">{r.interpreted_query}</span>
            <span className="text-ink-300">|</span>
            {r.matched_entities.map((m) => <Badge key={m.id} tone="blue" title={`${m.type} · matched "${m.surface}" via ${m.method}`}>{m.name}</Badge>)}
            {r.unresolved_terms.length > 0 && <Badge tone="amber" title={r.unresolved_terms.join("\n")}><AlertTriangle className="h-3 w-3" />{r.unresolved_terms.length} unresolved</Badge>}
            <span className="ml-auto flex items-center gap-2 text-ink-500">
              <StatusBadge status={r.validation_status} />
              <span>{r.retrieved_nodes.length} nodes · {r.retrieved_relationships.length} relationships · {allPaths.length} paths</span>
              <span>· {Math.round(r.latency_ms)} ms</span>
            </span>
          </div>
          <div className="flex min-h-0 flex-1">
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-center gap-2 border-b border-ink-100 bg-ink-50 px-4 py-2">
                <Tabs value={view} onChange={setView} tabs={[{ id: "tree", label: "Answer tree" }, { id: "graph", label: "Graph" }, { id: "paths", label: `Reasoning paths (${allPaths.length})` }, { id: "plan", label: "Query plan & validation" }]} />
                {(view === "tree" || view === "graph") && r.retrieved_nodes.length > 0 && (
                  <label className="ml-2 flex items-center gap-1.5 text-xs text-ink-500">root
                    <select value={rootId} onChange={(e) => { setRootId(e.target.value); setStepIdx(-1); }} className="max-w-[240px] rounded border border-ink-200 bg-white px-1.5 py-1 text-xs">
                      <option value="">{r.traversal?.virtual_root ? "query anchors (server)" : `${shortLabel(nodeMap.get(serverRoot)?.name || "auto", 30)} (server)`}</option>
                      {r.retrieved_nodes.slice().sort((a, b) => a.name.localeCompare(b.name)).map((n) => <option key={n.id} value={n.id}>{shortLabel(n.name, 40)} · {n.type}</option>)}
                    </select>
                  </label>
                )}
                {view === "graph" && <div className="ml-auto flex gap-1"><Button size="sm" onClick={() => graphRef.current?.fit()}><Maximize2 className="h-3.5 w-3.5" />Fit</Button>
                  <Button size="sm" onClick={() => downloadJSON(r)}><Download className="h-3.5 w-3.5" />Export</Button></div>}
                {activePath && <Button size="sm" variant="ghost" onClick={() => setActivePath(null)} className="ml-auto">Clear path highlight</Button>}
              </div>
              {(view === "tree" || view === "graph") && steps.length > 0 && (
                <div className="border-b border-ink-100 bg-white px-4 py-2"><TraversalPlayer steps={steps} nodes={nodeMap} onStep={onStep} strategy={strategy} /></div>
              )}
              <div className="relative min-h-0 flex-1">
                {view === "tree" && (r.retrieved_nodes.length ? (
                  <TreeView tree={tree} nodes={nodeMap} edges={edgeMap} visitOrder={visitOrder} currentNode={currentNode} pathNodes={pathNodes}
                    selectedId={sel?.node?.id} rootLabel={r.interpreted_query} onSelectNode={(n) => setSel({ node: n })} onSelectEdge={(e) => setSel({ edge: e })} />
                ) : <div className="p-6"><Empty>{r.answer_summary.text}</Empty></div>)}
                {view === "graph" && (
                  <>
                    <GraphCanvas ref={graphRef} nodes={r.retrieved_nodes} edges={r.retrieved_relationships} selectedId={sel?.node?.id} selectedEdgeId={sel?.edge?.id}
                      answerNodes={answerNodes} pathEdges={pathEdges} highlightNodes={pathNodes} visitOrder={visitOrder} currentNode={currentNode} dimOthers
                      onSelectNode={(n) => setSel(n ? { node: n } : null)} onSelectEdge={(e) => setSel({ edge: e })} />
                    <div className="absolute bottom-3 left-3 w-60 rounded-md border border-ink-200 bg-white/95 p-2.5 shadow-sm"><Legend /></div>
                  </>
                )}
                {view === "paths" && <PathsList paths={allPaths} nodes={nodeMap} edges={edgeMap} active={activePath} onPick={(p) => { setActivePath(p); setSel(null); }} onShow={(p) => { setActivePath(p); setView("graph"); }} />}
                {view === "plan" && <PlanView r={r} />}
              </div>
            </div>

            <aside className="flex w-[430px] shrink-0 flex-col border-l border-ink-200 bg-white">
              {sel?.node ? (
                <NodeDetail node={sel.node} onClose={() => setSel(null)} onView={setSource} />
              ) : sel?.edge ? (
                <EdgeDetail edge={sel.edge} nodes={nodeMap} onClose={() => setSel(null)} onView={setSource} />
              ) : null}
              <div className={`${sel ? "max-h-[45%] border-t border-ink-200" : "flex-1"} min-h-0 overflow-auto`}>
                {!sel && aiOn && r.query_id && (
                  <div className="border-b border-ink-100 px-3 py-3"><AiAnswer endpoint="/api/ai/explain/query" body={{ query_id: r.query_id }} runKey={r.query_id} title="AI explanation of these results" onSource={setSource} /></div>
                )}
                {!sel && (
                  <div className="border-b border-ink-100 px-4 py-3">
                    <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                      {r.answer_summary.status === "answered" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />}
                      Evidence-grounded answer <span className="font-normal normal-case text-ink-400">· {r.answer_summary.generator}</span>
                    </div>
                    <Markdownish text={r.answer_summary.text} />
                    {r.answer_summary.llm_text && <div className="mt-3 rounded bg-violet-50 p-2 text-[12.5px] text-ink-700"><div className="mb-1 text-[11px] font-semibold text-violet-700">Model rephrasing (citations verified)</div>{r.answer_summary.llm_text}</div>}
                    {Object.keys(r.answer_summary.statement_types).length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1">{Object.entries(r.answer_summary.statement_types).filter(([k]) => k !== "null").map(([k, v]) => <span key={k} className="flex items-center gap-1"><SupportBadge level={k} /><span className="text-[11px] text-ink-400">{v}</span></span>)}</div>
                    )}
                    {r.conflicts.length > 0 && <div className="mt-3 space-y-1">{r.conflicts.slice(0, 4).map((c, i) => <div key={i} className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[12px] text-amber-800"><b>{c.kind.replace(/_/g, " ")}:</b> {c.message}</div>)}</div>}
                    <p className="mt-3 text-[11px] leading-snug text-ink-400">{r.answer_summary.disclaimer}</p>
                  </div>
                )}
                <div className="px-4 py-3">
                  <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                    <span>Source evidence {sel || activePath ? "(filtered to selection)" : ""} · {passages.length}</span>
                    {sel && <button className="flex items-center gap-1 text-ink-500 normal-case hover:text-ink-800" onClick={() => setSel(null)}><ChevronLeft className="h-3 w-3" />answer</button>}
                  </div>
                  <div className="space-y-2">
                    {passages.length === 0 && <Empty>No protocol passages for this selection{sel?.edge && sel.edge.category !== "clinical" ? " — structural, terminology and mention links carry no clinical evidence" : ""}.</Empty>}
                    {passages.slice(0, 80).map((p, i) => (
                      <EvidenceCard key={p.claim_id + p.chunk_id + i} p={p} onView={setSource} active={sel?.edge?.id === p.edge_id}
                        onFocus={(eid) => { const e = edgeMap.get(eid); if (e) setSel({ edge: e }); }} />
                    ))}
                  </div>
                  {r.lexical_passages.length > 0 && !sel && (
                    <details className="mt-4">
                      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-ink-400">Lexical discovery · {r.lexical_passages.length} passages (no relationship implied)</summary>
                      <div className="mt-2 space-y-1.5">{r.lexical_passages.slice(0, 30).map((l: any) => (
                        <button key={l.chunk_id} onClick={() => setSource({ docId: l.doc_id, page: l.page_start, chunkId: l.chunk_id, title: l.title })}
                          className="block w-full rounded border border-ink-100 px-2 py-1.5 text-left text-[12px] text-ink-600 hover:bg-ink-50">
                          <span className="text-[11px] text-ink-400">{l.filename} · p.{l.page_start} · {l.section_title?.slice(0, 40)}</span><br />{l.text.slice(0, 220)}…
                        </button>))}</div>
                    </details>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </>
      )}
      <SourceViewer source={source} onClose={() => setSource(null)} />
    </div>
  );
}

function PathsList({ paths, nodes, edges, active, onPick, onShow }: { paths: (GPath & { label: string })[]; nodes: Map<string, GNode>; edges: Map<string, GEdge>; active: GPath | null; onPick: (p: GPath) => void; onShow: (p: GPath) => void }) {
  if (!paths.length) return <div className="p-6"><Empty>No multi-hop paths in this result.</Empty></div>;
  return (
    <div className="h-full overflow-auto p-4">
      <p className="mb-3 text-xs text-ink-500">Each path is a chain of stored relationships from the query anchor to an answer. Click to filter evidence to the path; "show in graph" highlights it.</p>
      <div className="space-y-2">
        {paths.slice(0, 120).map((p, i) => {
          const isActive = active && active.relationships.map((x) => x.edge_id).join() === p.relationships.map((x) => x.edge_id).join();
          return (
            <div key={i} onClick={() => onPick(p)} className={`cursor-pointer rounded-md border px-3 py-2 ${isActive ? "border-amber-300 bg-amber-50/50" : "border-ink-200 bg-white hover:border-ink-300"}`}>
              <div className="flex flex-wrap items-center gap-1 text-[12.5px]">
                <RouteIcon className="mr-1 h-3.5 w-3.5 text-ink-400" />
                <NodeChip n={nodes.get(p.nodes[0])} />
                {p.relationships.map((rel, j) => {
                  const e = edges.get(rel.edge_id);
                  return (
                    <span key={j} className="flex items-center gap-1">
                      <span className={`rounded px-1 text-[11px] ${e?.category === "clinical" ? "bg-ink-100 text-ink-600" : "bg-ink-50 text-ink-400"}`}>
                        {rel.direction === "forward" ? "" : "←"}{prettyRel(rel.type)}{rel.direction === "forward" ? "→" : ""}
                      </span>
                      <NodeChip n={nodes.get(p.nodes[j + 1])} />
                    </span>
                  );
                })}
              </div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-400">
                <span>{p.hops} hop{p.hops > 1 ? "s" : ""}</span><span>score {p.score?.toFixed(3)}</span><span>{p.label}</span>
                <span>{p.relationships.map((x) => edges.get(x.edge_id)?.support_level).filter(Boolean).map((s) => SUPPORT_LABEL[s!] || s).filter((v, k, a) => a.indexOf(v) === k).join(" · ")}</span>
                <button className="ml-auto inline-flex items-center gap-1 text-ink-600 hover:text-ink-900" onClick={(ev) => { ev.stopPropagation(); onShow(p); }}>show in graph <ArrowRight className="h-3 w-3" /></button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function NodeChip({ n }: { n?: GNode }) {
  if (!n) return <span className="text-ink-400">?</span>;
  return <span className="inline-flex items-center gap-1 font-medium text-ink-800"><span className="h-2 w-2 rounded-full" style={{ background: `var(--c, ${groupColor(n)})` }} />{shortLabel(n.name, 44)}</span>;
}
function groupColor(n: GNode) {
  return ({ trial: "#2563eb", intervention: "#7c3aed", condition: "#0d9488", biomarker: "#d97706", criterion: "#6b7280", outcome: "#16a34a", safety: "#be4b49", evidence: "#475569" } as any)[n.group] || "#94a3b8";
}

function PlanView({ r }: { r: QueryResponse }) {
  return (
    <div className="h-full space-y-3 overflow-auto p-4 text-[12.5px]">
      <Card title="Execution plan">
        <dl className="grid grid-cols-[140px_1fr] gap-y-1.5">
          <dt className="text-ink-400">Query id</dt><dd className="font-mono text-[11px]">{r.query_id}</dd>
          <dt className="text-ink-400">Intent</dt><dd>{r.intent}</dd>
          <dt className="text-ink-400">Primary retrieval</dt><dd>{r.retrieval_method.primary}</dd>
          <dt className="text-ink-400">Traversal</dt><dd>{r.retrieval_method.traversal}</dd>
          {r.retrieval_method.complementary && <><dt className="text-ink-400">Complementary</dt><dd>{r.retrieval_method.complementary}</dd></>}
        </dl>
        <div className="mt-3 space-y-2">
          {r.retrieval_method.templates.map((t: any, i: number) => (
            <div key={i} className="rounded border border-ink-200 bg-ink-50 px-3 py-2">
              <div className="font-mono text-[12px] font-medium text-ink-800">{t.name}</div>
              <div className="text-ink-500">{t.purpose}</div>
              <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-ink-600">{JSON.stringify(t.params, null, 1)}</pre>
            </div>
          ))}
        </div>
      </Card>
      <Card title={<span className="flex items-center gap-2">Retrieval validation <StatusBadge status={r.validation_status} /></span>}>
        <ul className="list-disc space-y-1 pl-5 text-ink-600">
          <li>Every returned relationship re-checked for existence in Neo4j.</li>
          <li>Clinical relationships require claim id, source document, chunk, page and quote; the claim's evidence must belong to the same document.</li>
          <li>Every graph path verified to be a chain of returned stored relationships.</li>
          <li>Semantic / lexical similarity is never used as proof of a relationship.</li>
        </ul>
        {r.validation_issues.length > 0 ? <div className="mt-2 space-y-1">{r.validation_issues.map((v, i) => <div key={i} className="rounded bg-rose-50 px-2 py-1 text-rose-700">{v}</div>)}</div>
          : <div className="mt-2 text-emerald-700">No validation issues.</div>}
      </Card>
      {(r.warnings.length > 0 || r.unresolved_terms.length > 0) && <Card title="Warnings & unresolved terms">
        {r.warnings.map((w, i) => <div key={i} className="text-amber-700">• {w}</div>)}
        {r.unresolved_terms.map((w, i) => <div key={i} className="text-ink-600">• unresolved: {w}</div>)}
      </Card>}
      {r.conflicts.length > 0 && <Card title="Differences / conflicts between sources">
        {r.conflicts.map((c, i) => <div key={i} className="mb-2"><b>{c.kind}</b>: {c.message}<pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-ink-500">{JSON.stringify(c.values, null, 1)}</pre></div>)}
      </Card>}
    </div>
  );
}

function StructuredBuilder({ onRun }: { onRun: (s: any) => void }) {
  const tpl = useQuery({ queryKey: ["templates"], queryFn: () => api.get<any[]>("/api/query/templates") });
  const [name, setName] = useState("trials_for_intervention");
  const [vals, setVals] = useState<Record<string, string>>({});
  const t = tpl.data?.find((x) => x.name === name);
  return (
    <div className="mt-3 rounded-md border border-ink-200 bg-ink-50 p-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-ink-500">Template<br />
          <select value={name} onChange={(e) => { setName(e.target.value); setVals({}); }} className="mt-1 rounded border border-ink-200 bg-white px-2 py-1 text-[12.5px]">
            {tpl.data?.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
          </select>
        </label>
        {t?.params.filter((p: string) => !["rels"].includes(p)).map((p: string) => (
          <EntityPicker key={p} label={p} value={vals[p] || ""} onChange={(v) => setVals((s) => ({ ...s, [p]: v }))} />
        ))}
        <Button variant="primary" onClick={() => onRun({ template: name, params: vals })}>Run structured query</Button>
      </div>
      {t && <p className="mt-2 text-xs text-ink-500">{t.description}. Only allowlisted, parameterised, read-only patterns can run.</p>}
    </div>
  );
}

export function EntityPicker({ label, value, onChange, type = "" }: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const res = useQuery({ queryKey: ["search", q, type], queryFn: () => api.get<any[]>(`/api/entities/search?q=${enc(q)}&limit=12${type ? `&type=${type}` : ""}`), enabled: q.length >= 2 });
  return (
    <label className="relative text-xs text-ink-500">{label}<br />
      <input value={open ? q : value} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 180)} onChange={(e) => setQ(e.target.value)}
        placeholder="search entity…" className="mt-1 w-64 rounded border border-ink-200 bg-white px-2 py-1 text-[12.5px] text-ink-800" />
      {open && res.data && res.data.length > 0 && (
        <div className="absolute z-20 mt-1 max-h-64 w-80 overflow-auto rounded-md border border-ink-200 bg-white shadow-lg">
          {res.data.map((e) => <button key={e.id} onMouseDown={() => { onChange(e.id); setQ(e.name); setOpen(false); }}
            className="block w-full px-2 py-1.5 text-left text-[12px] hover:bg-ink-50"><span className="text-ink-800">{e.name}</span> <span className="text-ink-400">· {e.type}</span></button>)}
        </div>
      )}
    </label>
  );
}

function downloadJSON(r: QueryResponse) {
  const blob = new Blob([JSON.stringify({ query: r.question, nodes: r.retrieved_nodes, relationships: r.retrieved_relationships, paths: r.graph_paths }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `subgraph-${r.query_id}.json`;
  a.click();
}
