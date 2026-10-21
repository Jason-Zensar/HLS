import { useMutation, useQuery } from "@tanstack/react-query";
import { Crosshair, Download, Expand, Maximize2, RefreshCw, Search, Workflow } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../App";
import { EdgeDetail, NodeDetail } from "../components/DetailPanel";
import GraphCanvas, { type GraphCanvasHandle } from "../components/GraphCanvas";
import Legend from "../components/Legend";
import SourceViewer, { type SourceRef } from "../components/SourceViewer";
import TraversalPlayer from "../components/TraversalPlayer";
import { Badge, Button, ErrorBox, Spinner, Tabs } from "../components/ui";
import { api, enc, type GEdge, type GNode, type Group } from "../lib/api";
import { GROUP_COLOR, prettyRel, shortLabel } from "../lib/graphStyle";
import type { Step } from "../lib/traverse";

const OVERVIEW_TYPES = ["Drug", "DrugClass", "CancerSubtype", "Disease", "Biomarker", "Endpoint", "Protocol", "AdverseEvent", "TreatmentSetting", "StudyDesign", "Intervention", "CombinationTherapy", "MolecularTarget", "StudyPhase", "ClinicalTrial", "Sponsor"];
const DEFAULT_TYPES = ["Drug", "DrugClass", "CancerSubtype", "Biomarker", "Endpoint", "Protocol"];
const REL_FILTERS = ["INVESTIGATES", "STUDIES", "ASSOCIATED_WITH_BIOMARKER", "HAS_PRIMARY_ENDPOINT", "HAS_SECONDARY_ENDPOINT", "COMBINED_WITH", "COMPARED_WITH",
  "MONITORS_ADVERSE_EVENT", "ASSOCIATED_ADVERSE_EVENT", "TARGETS", "HAS_SETTING", "HAS_DESIGN", "HAS_PHASE", "BELONGS_TO_CLASS", "SUBCLASS_OF", "VERSION_OF", "AMENDS",
  "INCLUDES_ARM", "USES_INTERVENTION", "HAS_INCLUSION_CRITERION", "HAS_EXCLUSION_CRITERION", "REFERENCES_CONDITION", "REFERENCES_DRUG", "HAS_DOSE_SPECIFICATION", "DOSE_OF", "SPONSORED_BY"];

export default function GraphExplorer() {
  const [params] = useSearchParams();
  const [types, setTypes] = useState<string[]>(DEFAULT_TYPES);
  const [limit, setLimit] = useState(140);
  const [docFilter, setDocFilter] = useState(params.get("doc") || "");
  const [phase, setPhase] = useState("");
  const [nodes, setNodes] = useState<GNode[]>([]);
  const [edges, setEdges] = useState<GEdge[]>([]);
  const [hiddenGroups, setHiddenGroups] = useState<Set<Group>>(new Set(["evidence"]));
  const [relFilter, setRelFilter] = useState<Set<string>>(new Set());
  const [labelMode, setLabelMode] = useState<"auto" | "all" | "none">("auto");
  const [sel, setSel] = useState<{ node?: GNode; edge?: GEdge } | null>(null);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<SourceRef | null>(null);
  const [strategy, setStrategy] = useState<"bfs" | "dfs">("bfs");
  const [depth, setDepth] = useState(2);
  const [steps, setSteps] = useState<Step[]>([]);
  const [stepIdx, setStepIdx] = useState(-1);
  const graphRef = useRef<GraphCanvasHandle>(null);
  const docs = useQuery({ queryKey: ["docs-mini"], queryFn: () => api.get("/api/documents?limit=1000") });

  const overview = useMutation({
    mutationFn: () => api.get(`/api/graph/overview?types=${types.join(",")}&limit=${limit}${docFilter ? `&doc_id=${docFilter}` : ""}${phase ? `&phase=${enc(phase)}` : ""}`),
    onSuccess: (d) => { setNodes(d.nodes); setEdges(d.edges); setSel(null); setSteps([]); setStepIdx(-1); },
  });
  useEffect(() => {
    const focus = params.get("focus");
    if (focus) expandFrom([focus], "bfs", 1, true);
    else overview.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const merge = (d: { nodes: GNode[]; edges: GEdge[] }, replace = false) => {
    setNodes((cur) => { const m = new Map(replace ? [] : cur.map((n) => [n.id, n])); d.nodes.forEach((n) => { if (!m.has(n.id)) m.set(n.id, n); }); return [...m.values()]; });
    setEdges((cur) => { const m = new Map(replace ? [] : cur.map((e) => [e.id, e])); d.edges.forEach((e) => m.set(e.id, e)); return [...m.values()]; });
  };

  const traverse = useMutation({
    mutationFn: (b: { seeds: string[]; strategy: string; max_depth: number }) => api.post("/api/graph/traverse", { ...b, max_nodes: 90, fanout: 10 }),
  });
  function expandFrom(seeds: string[], strat: "bfs" | "dfs", d: number, replace = false) {
    traverse.mutate({ seeds, strategy: strat, max_depth: d }, {
      onSuccess: (res) => {
        merge(res, replace);
        setSteps(res.order.map((s: any) => ({ ...s, edge: null })));
        setStepIdx(-1);
        setTimeout(() => graphRef.current?.focus(seeds[0]), 900);
      },
    });
  }

  const searchRes = useQuery({ queryKey: ["gsearch", search], queryFn: () => api.get<any[]>(`/api/entities/search?q=${enc(search)}&limit=12`), enabled: search.length >= 2 });

  const visible = useMemo(() => {
    const vn = nodes.filter((n) => !hiddenGroups.has(n.group));
    const ids = new Set(vn.map((n) => n.id));
    const ve = edges.filter((e) => ids.has(e.source) && ids.has(e.target) && (relFilter.size === 0 || relFilter.has(e.type)));
    return { nodes: vn, edges: ve };
  }, [nodes, edges, hiddenGroups, relFilter]);
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const visitOrder = useMemo(() => { const m = new Map<string, number>(); if (stepIdx >= 0) steps.slice(0, stepIdx + 1).forEach((s, i) => m.set(s.node, i)); return m; }, [steps, stepIdx]);
  const onStep = useCallback((i: number) => setStepIdx(i), []);
  const highlight = useMemo(() => new Set<string>(sel?.node ? [sel.node.id] : []), [sel]);

  const exportView = (kind: "json" | "svg") => {
    const data = kind === "json" ? JSON.stringify({ nodes: visible.nodes, relationships: visible.edges }, null, 2) : graphRef.current?.exportSVG() || "";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([data], { type: kind === "json" ? "application/json" : "image/svg+xml" }));
    a.download = `ctpip-graph.${kind}`;
    a.click();
  };

  const counts = useMemo(() => { const c: Record<string, number> = {}; visible.nodes.forEach((n) => (c[n.type] = (c[n.type] || 0) + 1)); return c; }, [visible.nodes]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Knowledge Graph Explorer" subtitle="Canonical entities connect protocol-specific contexts. Double-click a node to expand its neighbourhood; select a node to run a BFS / DFS traversal from it."
        actions={<>
          <Button onClick={() => graphRef.current?.fit()}><Maximize2 className="h-3.5 w-3.5" />Fit</Button>
          <Button onClick={() => overview.mutate()}><RefreshCw className="h-3.5 w-3.5" />Reset view</Button>
          <Button onClick={() => exportView("json")}><Download className="h-3.5 w-3.5" />JSON</Button>
          <Button onClick={() => exportView("svg")}><Download className="h-3.5 w-3.5" />SVG</Button>
        </>} />
      <div className="flex min-h-0 flex-1">
        {/* ---- filters */}
        <aside className="w-64 shrink-0 space-y-4 overflow-auto border-r border-ink-200 bg-white p-3 text-xs">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search node label / alias…"
              className="w-full rounded-md border border-ink-200 py-1.5 pl-7 pr-2 text-[12.5px] outline-none focus:ring-2 focus:ring-blue-500" />
            {searchRes.data && search.length >= 2 && (
              <div className="mt-1 max-h-60 overflow-auto rounded-md border border-ink-200 bg-white">
                {searchRes.data.length === 0 && <div className="px-2 py-2 text-ink-400">No match</div>}
                {searchRes.data.map((e) => (
                  <button key={e.id} onClick={() => { setSearch(""); if (nodeMap.has(e.id)) { graphRef.current?.focus(e.id); setSel({ node: nodeMap.get(e.id)! }); } else expandFrom([e.id], "bfs", 1); }}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-ink-50">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: GROUP_COLOR[e.group as Group] }} />
                    <span className="truncate text-ink-800">{e.name}</span><span className="ml-auto shrink-0 text-ink-400">{e.type}</span>
                  </button>))}
              </div>
            )}
          </div>
          <Section title="Overview content">
            <div className="flex flex-wrap gap-1">
              {OVERVIEW_TYPES.map((t) => (
                <button key={t} onClick={() => setTypes((s) => (s.includes(t) ? s.filter((x) => x !== t) : [...s, t]))}
                  className={`rounded border px-1.5 py-0.5 ${types.includes(t) ? "border-ink-700 bg-ink-800 text-white" : "border-ink-200 text-ink-600 hover:bg-ink-50"}`}>{t}</button>
              ))}
            </div>
            <label className="mt-2 block text-ink-500">Max nodes: {limit}<input type="range" min={30} max={400} step={10} value={limit} onChange={(e) => setLimit(+e.target.value)} className="w-full accent-ink-700" /></label>
            <label className="mt-1 block text-ink-500">Protocol / document
              <select value={docFilter} onChange={(e) => setDocFilter(e.target.value)} className="mt-0.5 w-full rounded border border-ink-200 px-1 py-1">
                <option value="">All protocols</option>
                {docs.data?.items?.filter((d: any) => d.status === "processed").map((d: any) => <option key={d.id} value={d.id}>{shortLabel(d.filename, 42)}</option>)}
              </select></label>
            <label className="mt-1 block text-ink-500">Study phase
              <select value={phase} onChange={(e) => setPhase(e.target.value)} className="mt-0.5 w-full rounded border border-ink-200 px-1 py-1">
                <option value="">Any phase</option>{["Phase 1", "Phase 1b", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"].map((p) => <option key={p}>{p}</option>)}
              </select></label>
            <Button className="mt-2 w-full justify-center" variant="primary" onClick={() => overview.mutate()}>Load overview</Button>
          </Section>
          <Section title="Show / hide categories"><Legend hidden={hiddenGroups} onToggle={(g) => setHiddenGroups((s) => { const n = new Set(s); n.has(g) ? n.delete(g) : n.add(g); return n; })} /></Section>
          <Section title={`Relationship filter ${relFilter.size ? `(${relFilter.size})` : "(all)"}`}>
            <div className="flex flex-wrap gap-1">
              {REL_FILTERS.map((r) => (
                <button key={r} onClick={() => setRelFilter((s) => { const n = new Set(s); n.has(r) ? n.delete(r) : n.add(r); return n; })}
                  className={`rounded border px-1.5 py-0.5 ${relFilter.has(r) ? "border-blue-600 bg-blue-600 text-white" : "border-ink-200 text-ink-600 hover:bg-ink-50"}`}>{prettyRel(r)}</button>
              ))}
            </div>
            {relFilter.size > 0 && <button className="mt-1 text-blue-700 hover:underline" onClick={() => setRelFilter(new Set())}>clear</button>}
          </Section>
          <Section title="Labels"><Tabs value={labelMode} onChange={setLabelMode} tabs={[{ id: "auto", label: "Auto" }, { id: "all", label: "All" }, { id: "none", label: "None" }]} /></Section>
        </aside>

        {/* ---- canvas */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 bg-ink-50 px-3 py-2 text-xs">
            <span className="text-ink-500">{visible.nodes.length} nodes · {visible.edges.length} relationships</span>
            <div className="flex flex-wrap gap-1">{Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t, c]) => <Badge key={t}>{t} {c}</Badge>)}</div>
            <div className="ml-auto flex items-center gap-2">
              <span className="text-ink-500">Traverse from selection</span>
              <Tabs value={strategy} onChange={setStrategy} tabs={[{ id: "bfs", label: "BFS" }, { id: "dfs", label: "DFS" }]} />
              <select value={depth} onChange={(e) => setDepth(+e.target.value)} className="rounded border border-ink-200 bg-white px-1 py-1">{[1, 2, 3, 4].map((d) => <option key={d} value={d}>depth {d}</option>)}</select>
              <Button size="sm" variant="primary" disabled={!sel?.node || traverse.isPending} onClick={() => sel?.node && expandFrom([sel.node.id], strategy, depth)}><Workflow className="h-3.5 w-3.5" />Traverse</Button>
              <Button size="sm" disabled={!sel?.node} onClick={() => sel?.node && expandFrom([sel.node.id], "bfs", 1)}><Expand className="h-3.5 w-3.5" />Expand</Button>
              <Button size="sm" disabled={!sel?.node} onClick={() => sel?.node && graphRef.current?.focus(sel.node.id)}><Crosshair className="h-3.5 w-3.5" />Focus</Button>
              <Button size="sm" disabled={!sel?.node} onClick={() => sel?.node && expandFrom([sel.node.id], "bfs", 1, true)}>Isolate</Button>
            </div>
          </div>
          {steps.length > 0 && <div className="border-b border-ink-100 bg-white px-3 py-2"><TraversalPlayer steps={steps} nodes={nodeMap} onStep={onStep} strategy={steps[0]?.structure === "stack" ? "dfs" : "bfs"} /></div>}
          <div className="relative min-h-0 flex-1">
            {(overview.isPending || traverse.isPending) && <div className="absolute left-3 top-3 z-10 rounded bg-white/90 px-2 py-1 shadow"><Spinner label="Loading graph…" /></div>}
            {(overview.error || traverse.error) && <div className="absolute left-3 top-3 z-10"><ErrorBox error={overview.error || traverse.error} /></div>}
            <GraphCanvas ref={graphRef} nodes={visible.nodes} edges={visible.edges} selectedId={sel?.node?.id} selectedEdgeId={sel?.edge?.id} labelMode={labelMode}
              visitOrder={visitOrder} currentNode={stepIdx >= 0 ? steps[stepIdx]?.node : null} dimOthers={stepIdx >= 0} highlightNodes={highlight}
              onSelectNode={(n) => setSel(n ? { node: n } : null)} onSelectEdge={(e) => setSel({ edge: e })} onExpandNode={(n) => expandFrom([n.id], "bfs", 1)} />
            {!visible.nodes.length && !overview.isPending && <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-400">No nodes for the current filters (has ingestion finished?)</div>}
          </div>
        </div>

        {/* ---- detail */}
        <aside className="w-[400px] shrink-0 border-l border-ink-200 bg-white">
          {sel?.node ? <NodeDetail node={sel.node} onClose={() => setSel(null)} onView={setSource} onExpand={(n) => expandFrom([n.id], "bfs", 1)} />
            : sel?.edge ? <EdgeDetail edge={sel.edge} nodes={nodeMap} onClose={() => setSel(null)} onView={setSource} />
              : <div className="space-y-3 p-4 text-[12.5px] text-ink-500">
                <p className="font-medium text-ink-700">Inspect nodes and relationships</p>
                <ul className="list-disc space-y-1 pl-4">
                  <li>Click a node for canonical name, aliases, source protocols, claims and pages.</li>
                  <li>Click an edge for its supporting passage, document, version, page and validation status.</li>
                  <li>Double-click to expand; use <b>Traverse</b> for a BFS / DFS expansion replayed step by step.</li>
                  <li>One canonical drug connects to many protocols; each protocol keeps its own evidence-bearing edge.</li>
                </ul>
                <div className="rounded-md border border-ink-200 p-3"><Legend /></div>
              </div>}
        </aside>
      </div>
      <SourceViewer source={source} onClose={() => setSource(null)} />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-400">{title}</div>{children}</div>;
}
