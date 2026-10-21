import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2, PlugZap, Save, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "../App";
import { Button, Card, ErrorBox } from "../components/ui";
import { api } from "../lib/api";
import { streamAi, useAiStatus } from "../lib/ai";

const RECOMMENDED = [
  { name: "qwen2.5:3b", note: "Default. Fast; fits a 4 GB graphics card (about 2 GB download)." },
  { name: "qwen2.5:7b", note: "Better writing and citations; needs about 6-8 GB of graphics memory (4.7 GB download)." },
  { name: "llama3.1:8b", note: "Good general model; about 8 GB of graphics memory (4.9 GB download)." },
];

export default function SettingsPage() {
  const qc = useQueryClient();
  const st = useAiStatus();
  const saved = useQuery({ queryKey: ["ai-settings"], queryFn: () => api.get("/api/ai/settings") });
  const [form, setForm] = useState<any>(null);
  useEffect(() => { if (saved.data && !form) setForm(saved.data); }, [saved.data, form]);
  const save = useMutation({ mutationFn: (f: any) => api.put("/api/ai/settings", f), onSuccess: (d) => { setForm(d); qc.invalidateQueries({ queryKey: ["ai-status"] }); qc.invalidateQueries({ queryKey: ["ai-settings"] }); } });
  const test = useMutation({ mutationFn: () => api.post("/api/ai/test") });
  const [pullName, setPullName] = useState("qwen2.5:3b");
  const [pull, setPull] = useState<{ running: boolean; status: string; pct: number | null; error?: string }>({ running: false, status: "", pct: null });
  const s = st.data;
  const doPull = () => {
    setPull({ running: true, status: "Starting download...", pct: null });
    streamAi("/api/ai/pull", { model: pullName }, (e) => {
      if (e.type === "progress") setPull({ running: true, status: e.error || e.status || "", pct: e.total ? Math.round((100 * (e.completed || 0)) / e.total) : null, error: e.error });
      if (e.type === "done") { setPull({ running: false, status: "Download finished", pct: 100 }); qc.invalidateQueries({ queryKey: ["ai-status"] }); }
      if (e.type === "error") setPull({ running: false, status: "", pct: null, error: e.message });
    }).catch((err) => setPull({ running: false, status: "", pct: null, error: err.message }));
  };
  const f = form;
  const set = (k: string, v: any) => setForm((x: any) => ({ ...x, [k]: v }));
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Settings" subtitle="Connect a local AI model (runs on this computer; protocol text never leaves it)." />
      <div className="flex-1 space-y-4 overflow-auto p-6">
        <Card title="Local AI status">
          {st.isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : s && (
            <div className="space-y-2 text-[13.5px]">
              <div className="flex items-center gap-2">
                {s.ready ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <XCircle className="h-5 w-5 text-rose-600" />}
                <b>{s.ready ? "Ready" : !s.enabled ? "Switched off" : "Not ready"}</b>
                <span className="text-ink-500">· {s.settings.provider === "ollama" ? "Ollama" : "OpenAI-compatible server"} at {s.settings.base_url} · model {s.settings.model}</span>
              </div>
              {s.error && <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">{s.error}</div>}
              {s.reachable && <div className="text-ink-600">Installed models: {s.models.map((m) => m.name).join(", ") || "none"}</div>}
              <div className="flex gap-2 pt-1">
                <Button onClick={() => test.mutate()} disabled={test.isPending || !s.ready}><PlugZap className="h-3.5 w-3.5" />{test.isPending ? "Testing..." : "Test the model"}</Button>
                {test.data && <span className="self-center text-emerald-700">Model replied "{test.data.reply}" in {test.data.latency_ms} ms</span>}
              </div>
              <ErrorBox error={test.error} />
            </div>
          )}
        </Card>

        {f && (
          <Card title="Model connection">
            <div className="grid max-w-3xl grid-cols-1 gap-4 text-[13.5px] md:grid-cols-2">
              <label className="flex items-center gap-2 md:col-span-2"><input type="checkbox" checked={!!f.enabled} onChange={(e) => set("enabled", e.target.checked)} className="h-4 w-4" />
                <span><b>Use local AI</b> - adds plain-language explanations, protocol study and the Ask AI assistant. Everything else works without it.</span></label>
              <label className="space-y-1"><span className="text-ink-600">Server type</span>
                <select value={f.provider} onChange={(e) => set("provider", e.target.value)} className="w-full rounded-md border border-ink-200 bg-white px-2 py-1.5">
                  <option value="ollama">Ollama (recommended)</option><option value="openai">OpenAI-compatible (LM Studio, llama.cpp, vLLM)</option></select></label>
              <label className="space-y-1"><span className="text-ink-600">Server address (host and port)</span>
                <input value={f.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="http://127.0.0.1:11434" className="w-full rounded-md border border-ink-200 px-2 py-1.5" />
                <span className="text-[11.5px] text-ink-400">Ollama's default port is 11434. LM Studio usually uses http://127.0.0.1:1234/v1.</span></label>
              <label className="space-y-1"><span className="text-ink-600">Model</span>
                <input list="ai-models" value={f.model} onChange={(e) => set("model", e.target.value)} className="w-full rounded-md border border-ink-200 px-2 py-1.5" />
                <datalist id="ai-models">{(s?.models || []).map((m) => <option key={m.name} value={m.name}>{m.parameters || ""}</option>)}</datalist>
                <span className="text-[11.5px] text-ink-400">Pick an installed model or type a name.</span></label>
              <label className="space-y-1"><span className="text-ink-600">Creativity (temperature): {Number(f.temperature).toFixed(1)}</span>
                <input type="range" min={0} max={1} step={0.1} value={f.temperature} onChange={(e) => set("temperature", Number(e.target.value))} className="w-full" />
                <span className="text-[11.5px] text-ink-400">Keep it low (0.1-0.3) for factual answers.</span></label>
              <label className="space-y-1"><span className="text-ink-600">Context size (tokens)</span>
                <select value={f.context_tokens} onChange={(e) => set("context_tokens", Number(e.target.value))} className="w-full rounded-md border border-ink-200 bg-white px-2 py-1.5">
                  {[4096, 8192, 12288, 16384, 32768].map((n) => <option key={n} value={n}>{n.toLocaleString()}</option>)}</select>
                <span className="text-[11.5px] text-ink-400">8,192 is a good balance; larger needs more memory.</span></label>
              {f.provider === "openai" && <label className="space-y-1"><span className="text-ink-600">API key (only if your server needs one)</span>
                <input type="password" value={f.api_key} onChange={(e) => set("api_key", e.target.value)} className="w-full rounded-md border border-ink-200 px-2 py-1.5" /></label>}
            </div>
            <div className="mt-4 flex items-center gap-2">
              <Button variant="primary" onClick={() => save.mutate(f)} disabled={save.isPending}><Save className="h-3.5 w-3.5" />{save.isPending ? "Saving..." : "Save settings"}</Button>
              {save.isSuccess && <span className="text-[12.5px] text-emerald-700">Saved</span>}
              <ErrorBox error={save.error} />
            </div>
          </Card>
        )}

        <Card title="Download a model (Ollama)">
          <div className="max-w-3xl space-y-3 text-[13.5px]">
            <ul className="space-y-1">{RECOMMENDED.map((r) => (
              <li key={r.name} className="flex items-start gap-2"><button onClick={() => setPullName(r.name)} className="rounded border border-ink-200 px-1.5 font-mono text-[12px] hover:bg-ink-50">{r.name}</button><span className="text-ink-600">{r.note}</span></li>))}</ul>
            <div className="flex gap-2">
              <input value={pullName} onChange={(e) => setPullName(e.target.value)} className="w-64 rounded-md border border-ink-200 px-2 py-1.5 font-mono text-[13px]" />
              <Button onClick={doPull} disabled={pull.running || !s?.reachable || s?.settings.provider !== "ollama"}><Download className="h-3.5 w-3.5" />{pull.running ? "Downloading..." : "Download"}</Button>
            </div>
            {(pull.status || pull.error) && (
              <div className="space-y-1">
                <div className={pull.error ? "text-rose-700" : "text-ink-600"}>{pull.error || pull.status}</div>
                {pull.pct != null && <div className="h-2 w-80 rounded bg-ink-100"><div className="h-2 rounded bg-violet-600" style={{ width: `${pull.pct}%` }} /></div>}
              </div>
            )}
            <p className="text-[12px] text-ink-500">After downloading, choose the model above and press Save. Ollama itself is installed from ollama.com; <code>start.bat</code> starts it automatically when it is installed.</p>
          </div>
        </Card>
      </div>
    </div>
  );
}
