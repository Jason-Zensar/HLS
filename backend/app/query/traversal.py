"""GraphRAG traversal: BFS / DFS over real graph edges.

Two uses:
1. `build_answer_tree` - organises a query's retrieved subgraph into a spanning tree rooted at the
   query anchors, records the visit order (with the queue / stack state at every step so the UI
   can replay BFS or DFS) and extracts root-to-answer reasoning paths. Only stored edges are used;
   the optional virtual "Query" root is marked `virtual` and is UI structure, not graph data.
2. `expand` - server-side BFS / DFS expansion in Neo4j from seed nodes (graph explorer), bounded
   by depth, fan-out and node budget, read-only.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from app.graph import neo4j_client as db
from app.graph.schema import primary_type

VIRTUAL_ROOT = "__query__"


def _adjacency(nodes: dict[str, dict], edges: list[dict]) -> dict[str, list[tuple[str, dict, str]]]:
    adj: dict[str, list[tuple[str, dict, str]]] = {n: [] for n in nodes}
    for e in edges:
        s, t = e["source"], e["target"]
        if s in adj and t in adj:
            adj[s].append((t, e, "out"))
            adj[t].append((s, e, "in"))
    for k in adj:  # deterministic: strongest evidence first
        adj[k].sort(key=lambda x: (-(x[1].get("confidence") or 0.5), x[0]))
    return adj


def build_answer_tree(nodes: dict[str, dict], edges: list[dict], roots: list[str], answer_ids: set[str],
                      strategy: str = "bfs", max_depth: int = 6) -> dict[str, Any]:
    roots = [r for r in roots if r in nodes]
    if not roots:
        # fall back to the highest-degree node as root
        deg: dict[str, int] = {}
        for e in edges:
            deg[e["source"]] = deg.get(e["source"], 0) + 1
            deg[e["target"]] = deg.get(e["target"], 0) + 1
        roots = [max(deg, key=deg.get)] if deg else list(nodes)[:1]
    adj = _adjacency(nodes, edges)
    virtual = len(roots) > 1
    order: list[dict] = []
    parent: dict[str, tuple[str | None, dict | None, str | None]] = {}
    depth: dict[str, int] = {}

    if strategy == "dfs":
        stack: list[tuple[str, str | None, dict | None, str | None, int]] = [(r, VIRTUAL_ROOT if virtual else None, None, None, 1 if virtual else 0) for r in reversed(roots)]
        while stack:
            nid, par, edge, direction, d = stack.pop()
            if nid in parent:
                continue
            parent[nid] = (par, edge, direction)
            depth[nid] = d
            order.append({"step": len(order), "node": nid, "depth": d, "parent": par, "edge": edge["id"] if edge else None,
                          "frontier": [s[0] for s in stack][-12:], "structure": "stack"})
            if d >= max_depth:
                continue
            for nb, e, dirn in reversed(adj.get(nid, [])):
                if nb not in parent:
                    stack.append((nb, nid, e, dirn, d + 1))
    else:
        queue: deque = deque()
        for r in roots:
            parent[r] = (VIRTUAL_ROOT if virtual else None, None, None)
            depth[r] = 1 if virtual else 0
            queue.append(r)
        while queue:
            nid = queue.popleft()
            order.append({"step": len(order), "node": nid, "depth": depth[nid], "parent": parent[nid][0],
                          "edge": parent[nid][1]["id"] if parent[nid][1] else None, "frontier": list(queue)[:12], "structure": "queue"})
            if depth[nid] >= max_depth:
                continue
            for nb, e, dirn in adj.get(nid, []):
                if nb not in parent:
                    parent[nb] = (nid, e, dirn)
                    depth[nb] = depth[nid] + 1
                    queue.append(nb)

    # nested tree
    children: dict[str, list[str]] = {}
    for nid, (par, _, _) in parent.items():
        if par is not None:
            children.setdefault(par, []).append(nid)

    def node_tree(nid: str, seen: set) -> dict:
        seen.add(nid)
        par, e, dirn = parent.get(nid, (None, None, None))
        out = {"id": nid, "depth": depth.get(nid, 0),
               "via": ({"edge_id": e["id"], "type": e["type"], "direction": dirn} if e else None),
               "is_answer": nid in answer_ids,
               "children": [node_tree(c, seen) for c in sorted(children.get(nid, []), key=lambda c: (c not in answer_ids, nodes[c]["name"] or "")) if c not in seen]}
        return out

    if virtual:
        tree = {"id": VIRTUAL_ROOT, "virtual": True, "depth": 0, "via": None, "is_answer": False,
                "children": [node_tree(r, set()) for r in roots]}
    else:
        tree = node_tree(roots[0], set())

    # reasoning paths root -> answer node, via parent pointers (all edges are stored relationships)
    paths = []
    for a in answer_ids:
        if a not in parent or a in roots:
            continue
        seq_nodes, seq_edges, cur = [a], [], a
        while parent.get(cur, (None,))[0] not in (None, VIRTUAL_ROOT):
            par, e, dirn = parent[cur]
            seq_edges.append({"edge_id": e["id"], "type": e["type"], "direction": "forward" if dirn == "out" else "reverse"})
            seq_nodes.append(par)
            cur = par
        seq_nodes.reverse()
        seq_edges.reverse()
        if seq_edges:
            score = 1.0
            for se in seq_edges:
                ed = next(x for x in edges if x["id"] == se["edge_id"])
                score *= (ed.get("confidence") or 0.6)
            score *= 0.92 ** (len(seq_edges) - 1)
            paths.append({"start": seq_nodes[0], "end": seq_nodes[-1], "nodes": seq_nodes, "relationships": seq_edges,
                          "hops": len(seq_edges), "score": round(score, 4), "source": strategy + "-tree"})
    paths.sort(key=lambda p: -p["score"])
    return {"strategy": strategy, "roots": roots, "virtual_root": virtual, "order": order, "tree": tree,
            "reasoning_paths": paths[:150], "unreached": [n for n in nodes if n not in parent]}


# ---------------------------------------------------------------------------
# Server-side expansion (explorer)
# ---------------------------------------------------------------------------
def expand(seed_ids: list[str], strategy: str, max_depth: int, rel_types: list[str], max_nodes: int = 80,
           fanout: int = 12) -> dict[str, Any]:
    from app.query.serialize import edge_json, node_json

    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    seen: set[str] = set()
    order: list[dict] = []
    seeds = db.read_records("MATCH (n:KG) WHERE n.id IN $ids RETURN n", {"ids": seed_ids})
    for r in seeds:
        nodes[r["n"]["id"]] = node_json(r["n"])

    def neighbours(ids: list[str]) -> list[Any]:
        return db.read_records("""
            UNWIND $ids AS nid
            MATCH (n:KG {id: nid})-[r]-(m:KG)
            WHERE type(r) IN $types AND NOT m:ExtractedClaim AND NOT m:EvidenceChunk AND NOT m:DocumentSection
            WITH n, r, m ORDER BY coalesce(r.extraction_confidence, 0.5) DESC
            WITH n, collect([r, m])[..$fan] AS pairs
            UNWIND pairs AS pr
            WITH n, pr[0] AS r, pr[1] AS m
            RETURN n.id AS src, r, m, startNode(r).id AS s, endNode(r).id AS t""", {"ids": ids, "types": rel_types, "fan": fanout})

    if strategy == "dfs":
        stack = [(s, None, 0) for s in reversed(seed_ids) if s in nodes]
        while stack and len(seen) < max_nodes:
            nid, par, d = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            order.append({"step": len(order), "node": nid, "depth": d, "parent": par, "frontier": [x[0] for x in stack][-10:], "structure": "stack"})
            if d >= max_depth:
                continue
            for rec in reversed(neighbours([nid])):
                m = rec["m"]
                nodes.setdefault(m["id"], node_json(m))
                ej = edge_json(rec["r"], rec["s"], rec["t"])
                edges.setdefault(ej["id"], ej)
                if m["id"] not in seen:
                    stack.append((m["id"], nid, d + 1))
    else:
        frontier = [s for s in seed_ids if s in nodes]
        parent: dict[str, str | None] = {s: None for s in frontier}
        d = 0
        while frontier and len(seen) < max_nodes:
            nxt = []
            for nid in frontier:
                if nid in seen:
                    continue
                seen.add(nid)
                order.append({"step": len(order), "node": nid, "depth": d, "parent": parent.get(nid), "frontier": nxt[:10], "structure": "queue"})
            if d >= max_depth:
                break
            for rec in neighbours(frontier):
                m = rec["m"]
                ej = edge_json(rec["r"], rec["s"], rec["t"])
                if len(nodes) >= max_nodes and m["id"] not in nodes:
                    continue
                nodes.setdefault(m["id"], node_json(m))
                edges.setdefault(ej["id"], ej)
                if m["id"] not in parent:
                    parent[m["id"]] = rec["src"]
                    nxt.append(m["id"])
            frontier = nxt
            d += 1
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "order": order, "strategy": strategy}
