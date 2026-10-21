import * as d3 from "d3";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { GEdge, GNode } from "../lib/api";
import { edgeColor, edgeDash, nodeColor, nodeRadius, prettyRel, shortLabel } from "../lib/graphStyle";

export interface GraphCanvasHandle {
  fit: () => void;
  focus: (id: string) => void;
  exportSVG: () => string;
}

interface Props {
  nodes: GNode[];
  edges: GEdge[];
  selectedId?: string | null;
  selectedEdgeId?: string | null;
  highlightNodes?: Set<string>;
  highlightEdges?: Set<string>;
  pathEdges?: Set<string>;
  visitOrder?: Map<string, number>;
  currentNode?: string | null;
  dimOthers?: boolean;
  labelMode?: "auto" | "all" | "none";
  answerNodes?: Set<string>;
  onSelectNode?: (n: GNode | null) => void;
  onSelectEdge?: (e: GEdge) => void;
  onExpandNode?: (n: GNode) => void;
  className?: string;
}

type SimNode = GNode & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode> & { e: GEdge; curve: number };

const GROUP_ANGLE: Record<string, number> = { trial: 0, intervention: 1, condition: 2, biomarker: 3, criterion: 4, outcome: 5, safety: 6, evidence: 7, other: 7 };

const GraphCanvas = forwardRef<GraphCanvasHandle, Props>(function GraphCanvas(props, ref) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const state = useRef<{ sim?: d3.Simulation<SimNode, SimLink>; zoom?: d3.ZoomBehavior<SVGSVGElement, unknown>; pos: Map<string, { x: number; y: number }>; k: number; nodes: SimNode[] }>({ pos: new Map(), k: 1, nodes: [] });
  const cb = useRef(props);
  cb.current = props;

  useImperativeHandle(ref, () => ({
    fit: () => fitView(),
    focus: (id: string) => focusNode(id),
    exportSVG: () => (svgRef.current ? new XMLSerializer().serializeToString(svgRef.current) : ""),
  }));

  function fitView(pad = 40) {
    const svg = svgRef.current;
    const st = state.current;
    if (!svg || !st.zoom || !st.nodes.length) return;
    const xs = st.nodes.map((n) => n.x ?? 0), ys = st.nodes.map((n) => n.y ?? 0);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const { width, height } = svg.getBoundingClientRect();
    const k = Math.min(2.2, 0.92 / Math.max((x1 - x0 + pad * 2) / width, (y1 - y0 + pad * 2) / height, 0.01));
    const t = d3.zoomIdentity.translate(width / 2 - (k * (x0 + x1)) / 2, height / 2 - (k * (y0 + y1)) / 2).scale(k);
    d3.select(svg).transition().duration(450).call(st.zoom.transform as any, t);
  }

  function focusNode(id: string) {
    const svg = svgRef.current;
    const st = state.current;
    const n = st.nodes.find((x) => x.id === id);
    if (!svg || !st.zoom || !n) return;
    const { width, height } = svg.getBoundingClientRect();
    const k = Math.max(st.k, 1.6);
    d3.select(svg).transition().duration(450).call(st.zoom.transform as any, d3.zoomIdentity.translate(width / 2 - k * (n.x ?? 0), height / 2 - k * (n.y ?? 0)).scale(k));
  }

  // ---- (re)build on data change ---------------------------------------------------
  useEffect(() => {
    const svgEl = svgRef.current!;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    let hovered: string | null = null;
    const { width, height } = svgEl.getBoundingClientRect();
    const st = state.current;

    const defs = svg.append("defs");
    ["#7c8597", "#2563eb", "#dc2626", "#a78bfa", "#94a3b8", "#cbd5e1", "#f59e0b"].forEach((c) => {
      defs.append("marker").attr("id", `arr-${c.slice(1)}`).attr("viewBox", "0 -5 10 10").attr("refX", 10).attr("refY", 0)
        .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
        .append("path").attr("d", "M0,-4L10,0L0,4").attr("fill", c);
    });

    const root = svg.append("g").attr("class", "zoom-layer");
    const gLinks = root.append("g").attr("class", "links");
    const gLinkLabels = root.append("g").attr("class", "link-labels");
    const gNodes = root.append("g").attr("class", "nodes");

    const nodes: SimNode[] = props.nodes.map((n) => {
      const p = st.pos.get(n.id);
      return { ...n, x: p?.x, y: p?.y };
    });
    const byId = new Map(nodes.map((n) => [n.id, n]));
    // parallel edges between the same pair get different curvature
    const pairCount = new Map<string, number>();
    const links: SimLink[] = props.edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => {
      const key = [e.source, e.target].sort().join("|");
      const c = pairCount.get(key) ?? 0;
      pairCount.set(key, c + 1);
      return { source: byId.get(e.source)!, target: byId.get(e.target)!, e, curve: c };
    });
    st.nodes = nodes;
    const deg = new Map<string, number>();
    links.forEach((l) => { deg.set((l.source as SimNode).id, (deg.get((l.source as SimNode).id) ?? 0) + 1); deg.set((l.target as SimNode).id, (deg.get((l.target as SimNode).id) ?? 0) + 1); });
    nodes.forEach((n) => { if (n.degree == null) n.degree = deg.get(n.id) ?? 0; });

    const R = Math.min(width, height) * 0.32;
    const sim = d3.forceSimulation<SimNode>(nodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance((l) => (l.e.category === "clinical" ? 70 : 55)).strength(0.55))
      .force("charge", d3.forceManyBody<SimNode>().strength((d) => -140 - nodeRadius(d) * 12).distanceMax(500))
      .force("collide", d3.forceCollide<SimNode>().radius((d) => nodeRadius(d) + 6))
      // gentle clustering of semantic groups around the centre -> organised, readable layout
      .force("x", d3.forceX<SimNode>((d) => Math.cos((GROUP_ANGLE[d.group] ?? 7) / 8 * 2 * Math.PI) * R * (d.type === "Protocol" ? 0.15 : 1)).strength(0.045))
      .force("y", d3.forceY<SimNode>((d) => Math.sin((GROUP_ANGLE[d.group] ?? 7) / 8 * 2 * Math.PI) * R * (d.type === "Protocol" ? 0.15 : 1)).strength(0.045))
      .alpha(st.pos.size ? 0.5 : 1).alphaDecay(0.035);
    st.sim = sim;

    const link = gLinks.selectAll<SVGPathElement, SimLink>("path").data(links).join("path")
      .attr("fill", "none").attr("stroke-linecap", "round").attr("class", "cursor-pointer")
      .on("click", (ev, d) => { ev.stopPropagation(); cb.current.onSelectEdge?.(d.e); })
      .on("mouseenter", function (_, d) { d3.select(this).attr("stroke-width", 3.2); linkLabel.filter((x) => x === d).attr("opacity", 1); })
      .on("mouseleave", function () { applyStyles(); });
    link.append("title").text((d) => `${prettyRel(d.e.type)}${d.e.props?.source_page_start ? ` · p.${d.e.props.source_page_start}` : ""}${d.e.multiplicity && d.e.multiplicity > 1 ? ` · ×${d.e.multiplicity}` : ""}`);

    const linkLabel = gLinkLabels.selectAll<SVGTextElement, SimLink>("text").data(links).join("text")
      .attr("font-size", 9).attr("fill", "#4a5263").attr("text-anchor", "middle").attr("pointer-events", "none")
      .attr("paint-order", "stroke").attr("stroke", "#ffffff").attr("stroke-width", 3)
      .text((d) => prettyRel(d.e.type));

    const node = gNodes.selectAll<SVGGElement, SimNode>("g").data(nodes, (d: any) => d.id).join("g")
      .attr("class", "cursor-pointer")
      .call(d3.drag<SVGGElement, SimNode>()
        .on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
        .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }))
      .on("click", (ev, d) => { ev.stopPropagation(); cb.current.onSelectNode?.(d); })
      .on("dblclick", (ev, d) => { ev.stopPropagation(); cb.current.onExpandNode?.(d); })
      .on("mouseenter", function (_, d) { hover(d.id); })
      .on("mouseleave", () => hover(null));

    node.append("circle").attr("class", "halo").attr("r", (d) => nodeRadius(d) + 5).attr("fill", "none").attr("stroke-width", 2.5);
    node.append("circle").attr("class", "body").attr("r", (d) => nodeRadius(d))
      .attr("fill", (d) => nodeColor(d)).attr("stroke", "#fff").attr("stroke-width", 1.5);
    node.filter((d) => d.scope === "document" && d.type !== "Protocol").select("circle.body").attr("stroke-dasharray", "2 1.5");
    node.filter((d) => ["unresolved", "ambiguous"].includes(d.props?.resolution_status)).select("circle.body").attr("stroke", "#f59e0b").attr("stroke-width", 2);
    node.append("text").attr("class", "order").attr("text-anchor", "middle").attr("dy", "0.35em").attr("font-size", 8.5)
      .attr("font-weight", 700).attr("fill", "#fff").attr("pointer-events", "none");
    node.append("text").attr("class", "label").attr("x", (d) => nodeRadius(d) + 4).attr("dy", "0.35em")
      .attr("font-size", 11).attr("fill", "#232733").attr("paint-order", "stroke").attr("stroke", "#fff").attr("stroke-width", 3.5)
      .attr("pointer-events", "none").text((d) => shortLabel(d.name, d.type === "Protocol" ? 34 : 30));
    node.append("title").text((d) => `${d.name}\n${d.type}${d.props?.nct_id ? " · " + d.props.nct_id : ""}`);

    svg.on("click", () => cb.current.onSelectNode?.(null));

    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.08, 6]).on("zoom", (ev) => {
      root.attr("transform", ev.transform.toString());
      st.k = ev.transform.k;
      applyLabels();
    });
    st.zoom = zoom;
    svg.call(zoom).on("dblclick.zoom", null);
    svg.call(zoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.85));

    function hover(id: string | null) { hovered = id; applyStyles(); }

    function neighbours(id: string) {
      const s = new Set<string>([id]);
      links.forEach((l) => { const a = (l.source as SimNode).id, b = (l.target as SimNode).id; if (a === id) s.add(b); if (b === id) s.add(a); });
      return s;
    }

    function applyLabels() {
      const P = cb.current;
      const k = st.k;
      const mode = P.labelMode ?? "auto";
      // progressive disclosure: only the ~25 most connected nodes are labelled until the user zooms in
      const degs = nodes.map((n) => n.degree ?? 0).sort((x, y) => y - x);
      const cut = degs[Math.min(degs.length - 1, 24)] ?? 0;
      node.select<SVGTextElement>("text.label").attr("display", (d) => {
        if (mode === "none") return "none";
        if (mode === "all") return null;
        const important = d.id === P.selectedId || d.id === hovered || P.highlightNodes?.has(d.id) || P.answerNodes?.has(d.id) || P.visitOrder?.has(d.id);
        if (important) return null;
        const big = nodes.length <= 30 || (d.degree ?? 0) > cut || ((d.degree ?? 0) === cut && cut > 0);
        return k > 1.8 || (big && k > 0.45) ? null : "none";
      });
      linkLabel.attr("display", (d) => {
        const P2 = cb.current;
        const hl = P2.highlightEdges?.has(d.e.id) || P2.pathEdges?.has(d.e.id) || d.e.id === P2.selectedEdgeId;
        return hl || k > 2.2 || (links.length < 40 && k > 0.9) ? null : "none";
      });
    }

    function applyStyles() {
      const P = cb.current;
      const focusSet = hovered ? neighbours(hovered) : P.selectedId ? neighbours(P.selectedId) : null;
      const hasHL = (P.highlightNodes && P.highlightNodes.size > 0) || (P.visitOrder && P.visitOrder.size > 0);
      const nodeActive = (id: string) => {
        if (focusSet && hovered) return focusSet.has(id);
        if (P.visitOrder && P.visitOrder.size) return P.visitOrder.has(id);
        if (P.highlightNodes && P.highlightNodes.size) return P.highlightNodes.has(id);
        return true;
      };
      node.attr("opacity", (d) => (P.dimOthers && hasHL && !nodeActive(d.id) ? 0.14 : focusSet && hovered && !focusSet.has(d.id) ? 0.3 : 1));
      node.select("circle.halo").attr("stroke", (d) =>
        d.id === P.currentNode ? "#f59e0b" : d.id === P.selectedId ? "#151821" : P.answerNodes?.has(d.id) ? "#16a34a" : "transparent")
        .attr("stroke-dasharray", (d) => (P.answerNodes?.has(d.id) && d.id !== P.selectedId ? "3 2" : null));
      node.select<SVGTextElement>("text.order").text((d) => (P.visitOrder?.has(d.id) ? String(P.visitOrder.get(d.id)! + 1) : ""));
      link.attr("stroke", (d) => {
        if (d.e.id === P.selectedEdgeId) return "#151821";
        if (P.pathEdges?.has(d.e.id)) return "#f59e0b";
        if (P.highlightEdges?.has(d.e.id)) return "#2563eb";
        return edgeColor(d.e);
      }).attr("stroke-width", (d) => (d.e.id === P.selectedEdgeId ? 3 : P.pathEdges?.has(d.e.id) ? 3 : P.highlightEdges?.has(d.e.id) ? 2.2 : d.e.category === "clinical" ? 1.4 + Math.min(2, (d.e.multiplicity ?? 1) / 4) : 1))
        .attr("stroke-dasharray", (d) => edgeDash(d.e))
        .attr("marker-end", (d) => {
          const c = d.e.id === P.selectedEdgeId ? "#7c8597" : P.pathEdges?.has(d.e.id) ? "#f59e0b" : P.highlightEdges?.has(d.e.id) ? "#2563eb" : edgeColor(d.e);
          return `url(#arr-${c.slice(1)})`;
        })
        .attr("opacity", (d) => {
          const a = (d.source as SimNode).id, b = (d.target as SimNode).id;
          if (focusSet && hovered) return focusSet.has(a) && focusSet.has(b) ? 1 : 0.08;
          if (P.dimOthers && hasHL) {
            if (P.visitOrder && P.visitOrder.size) return P.visitOrder.has(a) && P.visitOrder.has(b) ? 0.95 : 0.06;
            return P.highlightEdges?.has(d.e.id) || P.pathEdges?.has(d.e.id) ? 1 : 0.07;
          }
          return d.e.category === "mention" ? 0.45 : 0.85;
        });
      linkLabel.attr("opacity", 0.95);
      applyLabels();
    }
    (svgEl as any).__applyStyles = applyStyles;

    function linkPath(d: SimLink) {
      const s = d.source as SimNode, t = d.target as SimNode;
      const dx = (t.x ?? 0) - (s.x ?? 0), dy = (t.y ?? 0) - (s.y ?? 0);
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const rt = nodeRadius(t) + 3, rs = nodeRadius(s);
      const sx = (s.x ?? 0) + (dx / dist) * rs, sy = (s.y ?? 0) + (dy / dist) * rs;
      const tx = (t.x ?? 0) - (dx / dist) * rt, ty = (t.y ?? 0) - (dy / dist) * rt;
      if (!d.curve) return `M${sx},${sy}L${tx},${ty}`;
      const off = 18 * Math.ceil(d.curve / 2) * (d.curve % 2 ? 1 : -1);
      const mx = (sx + tx) / 2 - (dy / dist) * off, my = (sy + ty) / 2 + (dx / dist) * off;
      return `M${sx},${sy}Q${mx},${my} ${tx},${ty}`;
    }

    sim.on("tick", () => {
      link.attr("d", linkPath);
      linkLabel.attr("x", (d) => (((d.source as SimNode).x ?? 0) + ((d.target as SimNode).x ?? 0)) / 2)
        .attr("y", (d) => (((d.source as SimNode).y ?? 0) + ((d.target as SimNode).y ?? 0)) / 2 - 3);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });
    sim.on("end", () => { nodes.forEach((n) => st.pos.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 })); });
    let fitted = false;
    const t = setTimeout(() => { if (!fitted) { fitted = true; fitView(); } }, nodes.length > 150 ? 1400 : 900);
    applyStyles();
    return () => { clearTimeout(t); sim.stop(); nodes.forEach((n) => st.pos.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 })); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.nodes, props.edges]);

  // ---- restyle without relayout -------------------------------------------------------
  useEffect(() => {
    const f = (svgRef.current as any)?.__applyStyles;
    if (f) f();
  }, [props.selectedId, props.selectedEdgeId, props.highlightNodes, props.highlightEdges, props.pathEdges, props.visitOrder, props.currentNode, props.dimOthers, props.labelMode, props.answerNodes]);

  return (
    <div ref={wrap} className={props.className ?? "relative h-full w-full"}>
      <svg ref={svgRef} className="h-full w-full select-none bg-white" role="img" aria-label="Knowledge graph" />
    </div>
  );
});

export default GraphCanvas;
