// Client-side BFS / DFS over a returned subgraph (only real edges from the backend).
import type { GEdge } from "./api";

export interface Step { step: number; node: string; depth: number; parent: string | null; edge: string | null; frontier: string[]; structure: "queue" | "stack" }

export function adjacency(nodeIds: string[], edges: GEdge[]) {
  const adj = new Map<string, { nb: string; edge: GEdge }[]>();
  nodeIds.forEach((n) => adj.set(n, []));
  for (const e of edges) {
    if (!adj.has(e.source) || !adj.has(e.target)) continue;
    adj.get(e.source)!.push({ nb: e.target, edge: e });
    adj.get(e.target)!.push({ nb: e.source, edge: e });
  }
  for (const list of adj.values()) list.sort((a, b) => (b.edge.confidence ?? 0.5) - (a.edge.confidence ?? 0.5) || a.nb.localeCompare(b.nb));
  return adj;
}

export function bfs(root: string, nodeIds: string[], edges: GEdge[], maxDepth = 8): Step[] {
  const adj = adjacency(nodeIds, edges);
  const seen = new Map<string, { parent: string | null; edge: string | null; depth: number }>();
  const q: string[] = [root];
  seen.set(root, { parent: null, edge: null, depth: 0 });
  const out: Step[] = [];
  while (q.length) {
    const n = q.shift()!;
    const meta = seen.get(n)!;
    out.push({ step: out.length, node: n, depth: meta.depth, parent: meta.parent, edge: meta.edge, frontier: [...q].slice(0, 14), structure: "queue" });
    if (meta.depth >= maxDepth) continue;
    for (const { nb, edge } of adj.get(n) || []) {
      if (!seen.has(nb)) { seen.set(nb, { parent: n, edge: edge.id, depth: meta.depth + 1 }); q.push(nb); }
    }
  }
  return out;
}

export function dfs(root: string, nodeIds: string[], edges: GEdge[], maxDepth = 8): Step[] {
  const adj = adjacency(nodeIds, edges);
  const visited = new Set<string>();
  const stack: { n: string; parent: string | null; edge: string | null; depth: number }[] = [{ n: root, parent: null, edge: null, depth: 0 }];
  const out: Step[] = [];
  while (stack.length) {
    const cur = stack.pop()!;
    if (visited.has(cur.n)) continue;
    visited.add(cur.n);
    out.push({ step: out.length, node: cur.n, depth: cur.depth, parent: cur.parent, edge: cur.edge, frontier: stack.map((s) => s.n).slice(-14).reverse(), structure: "stack" });
    if (cur.depth >= maxDepth) continue;
    const nbs = adj.get(cur.n) || [];
    for (let i = nbs.length - 1; i >= 0; i--) {
      if (!visited.has(nbs[i].nb)) stack.push({ n: nbs[i].nb, parent: cur.n, edge: nbs[i].edge.id, depth: cur.depth + 1 });
    }
  }
  return out;
}

/** Build a nested tree from traversal steps (parent pointers). */
export interface TNode { id: string; edge: string | null; depth: number; children: TNode[] }
export function stepsToTree(steps: Step[]): TNode | null {
  if (!steps.length) return null;
  const map = new Map<string, TNode>();
  steps.forEach((s) => map.set(s.node, { id: s.node, edge: s.edge, depth: s.depth, children: [] }));
  let root: TNode | null = null;
  for (const s of steps) {
    const t = map.get(s.node)!;
    if (s.parent && map.has(s.parent)) map.get(s.parent)!.children.push(t);
    else if (!root) root = t;
  }
  return root;
}
