import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GEdge, GNode } from "../lib/api";
import { nodeColor, prettyRel, shortLabel } from "../lib/graphStyle";

export interface UTree { id: string; via?: { edge_id: string; type: string; direction: string } | null; is_answer?: boolean; virtual?: boolean; children: UTree[] }

interface Props {
  tree: UTree | null;
  nodes: Map<string, GNode>;
  edges: Map<string, GEdge>;
  visitOrder?: Map<string, number>;
  currentNode?: string | null;
  pathNodes?: Set<string>;
  selectedId?: string | null;
  onSelectNode?: (n: GNode) => void;
  onSelectEdge?: (e: GEdge) => void;
  rootLabel?: string;
}

export default function TreeView({ tree, nodes, edges, visitOrder, currentNode, pathNodes, selectedId, onSelectNode, onSelectEdge, rootLabel }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown>>();
  const gRef = useRef<SVGGElement | null>(null);

  useEffect(() => setCollapsed(new Set()), [tree]);

  const data = useMemo(() => {
    if (!tree) return null;
    const prune = (t: UTree, path: string): any => ({
      ...t, key: path, children: collapsed.has(path) ? [] : t.children.map((c, i) => prune(c, `${path}/${i}`)),
      _hidden: collapsed.has(path) ? t.children.length : 0,
    });
    return prune(tree, "r");
  }, [tree, collapsed]);

  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    svg.selectAll("*").remove();
    if (!data) return;
    const { width, height } = svgRef.current!.getBoundingClientRect();
    const root = d3.hierarchy<any>(data, (d) => d.children);
    const leaves = root.leaves().length;
    const dx = 26, dy = 230;
    d3.tree<any>().nodeSize([dx, dy])(root);
    const g = svg.append("g");
    gRef.current = g.node();
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.15, 3]).on("zoom", (ev) => g.attr("transform", ev.transform.toString()));
    zoomRef.current = zoom;
    svg.call(zoom).on("dblclick.zoom", null);
    let x0 = Infinity, x1 = -Infinity;
    root.each((d: any) => { x0 = Math.min(x0, d.x); x1 = Math.max(x1, d.x); });
    const k = Math.min(1, Math.max(0.35, height / (x1 - x0 + 80)));
    svg.call(zoom.transform, d3.zoomIdentity.translate(60, height / 2 - ((x0 + x1) / 2) * k).scale(k));

    // links
    const lg = g.append("g").attr("fill", "none");
    lg.selectAll("path").data(root.links()).join("path")
      .attr("d", d3.linkHorizontal<any, any>().x((d: any) => d.y).y((d: any) => d.x) as any)
      .attr("stroke", (d: any) => (pathNodes?.has(d.target.data.id) && pathNodes?.has(d.source.data.id) ? "#f59e0b" : visitOrder?.has(d.target.data.id) ? "#2563eb" : "#c3c9d4"))
      .attr("stroke-width", (d: any) => (pathNodes?.has(d.target.data.id) && pathNodes?.has(d.source.data.id) ? 2.6 : visitOrder?.has(d.target.data.id) ? 1.8 : 1.2))
      .attr("stroke-dasharray", (d: any) => {
        const e = d.target.data.via ? edges.get(d.target.data.via.edge_id) : null;
        return d.source.data.virtual ? "3 3" : e && e.category !== "clinical" ? "2 3" : null;
      });
    // edge labels (relationship + direction)
    g.append("g").selectAll("text").data(root.links().filter((l: any) => l.target.data.via)).join("text")
      .attr("x", (d: any) => (d.source.y + d.target.y) / 2).attr("y", (d: any) => (d.source.x + d.target.x) / 2 - 4)
      .attr("text-anchor", "middle").attr("font-size", 9.5).attr("fill", "#646d7f").attr("class", "cursor-pointer")
      .attr("paint-order", "stroke").attr("stroke", "#fff").attr("stroke-width", 3)
      .text((d: any) => (d.target.data.via.direction === "out" || d.target.data.via.direction === "forward" ? `${prettyRel(d.target.data.via.type)} →` : `← ${prettyRel(d.target.data.via.type)}`))
      .on("click", (_, d: any) => { const e = edges.get(d.target.data.via.edge_id); if (e) onSelectEdge?.(e); })
      .append("title").text("Click to inspect this relationship's evidence");

    // nodes
    const ng = g.append("g").selectAll("g").data(root.descendants()).join("g")
      .attr("transform", (d: any) => `translate(${d.y},${d.x})`).attr("class", "cursor-pointer")
      .on("click", (_, d: any) => { const n = nodes.get(d.data.id); if (n) onSelectNode?.(n); })
      .on("dblclick", (_, d: any) => {
        setCollapsed((s) => { const c = new Set(s); c.has(d.data.key) ? c.delete(d.data.key) : c.add(d.data.key); return c; });
      });
    ng.append("circle").attr("r", (d: any) => (d.data.virtual ? 7 : 6.5))
      .attr("fill", (d: any) => (d.data.virtual ? "#fff" : nodeColor(nodes.get(d.data.id) || ({ group: "other" } as any))))
      .attr("stroke", (d: any) => (d.data.id === currentNode ? "#f59e0b" : d.data.id === selectedId ? "#151821" : d.data.is_answer ? "#16a34a" : d.data.virtual ? "#646d7f" : "#fff"))
      .attr("stroke-width", (d: any) => (d.data.id === currentNode || d.data.id === selectedId || d.data.is_answer ? 3 : 1.5))
      .attr("stroke-dasharray", (d: any) => (d.data.virtual ? "2 2" : null))
      .attr("opacity", (d: any) => (visitOrder && visitOrder.size && !d.data.virtual && !visitOrder.has(d.data.id) ? 0.25 : 1));
    ng.filter((d: any) => !!visitOrder?.has(d.data.id)).append("text").attr("x", -10).attr("dy", "0.35em").attr("text-anchor", "end")
      .attr("font-size", 9).attr("font-weight", 700).attr("fill", "#2563eb").text((d: any) => `#${visitOrder!.get(d.data.id)! + 1}`);
    ng.append("text").attr("x", 11).attr("dy", "0.35em").attr("font-size", 11.5)
      .attr("font-weight", (d: any) => (d.data.is_answer || d.depth === 0 ? 600 : 400)).attr("fill", "#232733")
      .attr("paint-order", "stroke").attr("stroke", "#fff").attr("stroke-width", 3)
      .text((d: any) => {
        if (d.data.virtual) return rootLabel || "Query";
        const n = nodes.get(d.data.id);
        const lab = shortLabel(n?.name || d.data.id, 36);
        return d.data._hidden ? `${lab}  (+${d.data._hidden})` : lab;
      })
      .attr("opacity", (d: any) => (visitOrder && visitOrder.size && !d.data.virtual && !visitOrder.has(d.data.id) ? 0.35 : 1));
    ng.append("title").text((d: any) => {
      const n = nodes.get(d.data.id);
      return d.data.virtual ? "Query root (UI structure, not a graph node)" : `${n?.name}\n${n?.type}\nDouble-click to collapse / expand`;
    });
    void leaves; void width;
  }, [data, visitOrder, currentNode, pathNodes, selectedId, nodes, edges, onSelectNode, onSelectEdge, rootLabel]);

  if (!tree) return <div className="flex h-full items-center justify-center text-sm text-ink-400">No tree to display</div>;
  return (
    <div className="relative h-full w-full">
      <svg ref={svgRef} className="h-full w-full bg-white" role="img" aria-label="Answer tree" />
      <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-ink-400">Scroll to zoom · drag to pan · double-click a node to collapse/expand · click a relationship label for evidence</div>
    </div>
  );
}
