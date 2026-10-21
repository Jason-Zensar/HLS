import { Pause, Play, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { GNode } from "../lib/api";
import type { Step } from "../lib/traverse";
import { shortLabel } from "../lib/graphStyle";
import { Button } from "./ui";

/** Replays a BFS / DFS visit sequence: current node, visited set and the queue / stack at every step. */
export default function TraversalPlayer({ steps, nodes, onStep, strategy }: { steps: Step[]; nodes: Map<string, GNode>; onStep: (idx: number) => void; strategy: string }) {
  const [idx, setIdx] = useState(steps.length - 1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(450);
  const timer = useRef<number>();
  useEffect(() => { setIdx(steps.length - 1); setPlaying(false); }, [steps]);
  useEffect(() => { onStep(idx); }, [idx, onStep]);
  useEffect(() => {
    if (!playing) return;
    timer.current = window.setTimeout(() => {
      setIdx((i) => { if (i >= steps.length - 1) { setPlaying(false); return i; } return i + 1; });
    }, speed);
    return () => window.clearTimeout(timer.current);
  }, [playing, idx, speed, steps.length]);
  if (!steps.length) return null;
  const cur = steps[Math.max(0, idx)];
  const name = (id: string) => shortLabel(nodes.get(id)?.name || (id === "__query__" ? "Query" : id), 26);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-ink-200 bg-white px-3 py-2 text-xs">
      <div className="flex items-center gap-1">
        <Button size="sm" onClick={() => { setPlaying(false); setIdx(0); }} title="First step"><SkipBack className="h-3.5 w-3.5" /></Button>
        <Button size="sm" onClick={() => setIdx((i) => Math.max(0, i - 1))} title="Previous step">‹</Button>
        <Button size="sm" variant="primary" onClick={() => { if (idx >= steps.length - 1) setIdx(0); setPlaying((p) => !p); }} title={playing ? "Pause" : "Play traversal"}>
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </Button>
        <Button size="sm" onClick={() => setIdx((i) => Math.min(steps.length - 1, i + 1))} title="Next step">›</Button>
        <Button size="sm" onClick={() => { setPlaying(false); setIdx(steps.length - 1); }} title="Show all"><SkipForward className="h-3.5 w-3.5" /></Button>
        <Button size="sm" variant="ghost" onClick={() => { setPlaying(false); setIdx(-1); }} title="Clear traversal overlay"><RotateCcw className="h-3.5 w-3.5" /></Button>
      </div>
      <label className="flex items-center gap-1 text-ink-500">speed
        <input type="range" min={120} max={1200} step={60} value={1320 - speed} onChange={(e) => setSpeed(1320 - Number(e.target.value))} className="w-20 accent-ink-700" />
      </label>
      <div className="tabular-nums text-ink-600"><b className="uppercase">{strategy}</b> step {idx + 1}/{steps.length}</div>
      {idx >= 0 && cur && (
        <div className="flex min-w-0 flex-1 items-center gap-2 text-ink-600">
          <span className="shrink-0">visiting <b className="text-ink-900">{name(cur.node)}</b> (depth {cur.depth})</span>
          <span className="shrink-0 text-ink-400">{cur.structure === "queue" ? "queue →" : "stack (top first) →"}</span>
          <div className="flex min-w-0 gap-1 overflow-hidden">
            {cur.frontier.length === 0 && <span className="text-ink-400">empty</span>}
            {cur.frontier.slice(0, 8).map((f, i) => <span key={f + i} className="truncate rounded bg-ink-100 px-1.5 py-0.5 text-ink-600">{name(f)}</span>)}
            {cur.frontier.length > 8 && <span className="text-ink-400">+{cur.frontier.length - 8}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
