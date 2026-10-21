import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Activity, BookOpen, Bot, Columns3, GitBranch, History, LayoutDashboard, Network, Search, Settings, Sparkles } from "lucide-react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./lib/api";
import { useAiStatus } from "./lib/ai";
import AssistantPage from "./pages/Assistant";
import ComparePage from "./pages/Compare";
import Dashboard from "./pages/Dashboard";
import DocumentDetail from "./pages/DocumentDetail";
import Documents from "./pages/Documents";
import GraphExplorer from "./pages/GraphExplorer";
import HistoryPage from "./pages/History";
import SearchPage from "./pages/Search";
import SettingsPage from "./pages/Settings";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true, hint: "Summary and data quality" },
  { to: "/documents", label: "Protocols", icon: BookOpen, hint: "Study any protocol" },
  { to: "/assistant", label: "Ask AI", icon: Sparkles, hint: "Questions about one or all protocols" },
  { to: "/search", label: "Search", icon: Search, hint: "Find trials by drug, disease, outcome or wording" },
  { to: "/compare", label: "Compare", icon: Columns3, hint: "Protocols side by side" },
  { to: "/graph", label: "Knowledge Graph", icon: Network, hint: "Explore connections visually" },
  { to: "/history", label: "History", icon: History, hint: "Past questions and activity log" },
  { to: "/settings", label: "Settings", icon: Settings, hint: "Local AI model" },
];

export default function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get("/api/health"), refetchInterval: 15_000 });
  const ai = useAiStatus();
  const online = health.data?.graph === "online";
  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-ink-200 bg-white">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-violet-700 text-white"><GitBranch className="h-4 w-4" /></div>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold text-ink-900">CTPIP</div>
            <div className="text-[10.5px] text-ink-400">Clinical Trial Protocols</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.map(({ to, label, icon: Icon, end, hint }) => (
            <NavLink key={to} to={to} end={end} title={hint}
              className={({ isActive }) => clsx("flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] transition",
                isActive ? "bg-violet-50 font-medium text-violet-900" : "text-ink-600 hover:bg-ink-50 hover:text-ink-800")}>
              <Icon className="h-4 w-4" />{label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-1.5 border-t border-ink-100 px-4 py-3 text-[11px] text-ink-500">
          <div className="flex items-center gap-1.5"><span className={clsx("h-2 w-2 rounded-full", online ? "bg-emerald-500" : "bg-rose-500")} />
            Database {health.data ? (online ? "online" : "offline") : "..."}</div>
          <NavLink to="/settings" className="flex items-center gap-1.5 hover:text-ink-800"><span className={clsx("h-2 w-2 rounded-full", ai.data?.ready ? "bg-emerald-500" : ai.data && !ai.data.enabled ? "bg-ink-300" : "bg-amber-500")} />
            <Bot className="h-3 w-3" />Local AI {ai.data ? (ai.data.ready ? ai.data.settings.model : !ai.data.enabled ? "off" : "not ready") : "..."}</NavLink>
          {health.data?.worker && (health.data.worker.running_jobs > 0 || health.data.worker.queued > 0) &&
            <div className="flex items-center gap-1.5"><Activity className="h-3 w-3" /> reading {health.data.worker.running_jobs} · waiting {health.data.worker.queued}</div>}
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:docId" element={<DocumentDetail />} />
          <Route path="/assistant" element={<AssistantPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/query" element={<LegacySearch tab="graph" />} />
          <Route path="/evidence" element={<LegacySearch tab="text" />} />
          <Route path="/graph" element={<GraphExplorer />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/quality" element={<Navigate to="/#quality" replace />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}

/** Old addresses (/query, /evidence) open the matching Search tab and keep the question. */
function LegacySearch({ tab }: { tab: "graph" | "text" }) {
  const loc = useLocation();
  const p = new URLSearchParams(loc.search);
  p.set("tab", tab);
  return <Navigate to={`/search?${p.toString()}`} replace />;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-4 border-b border-ink-200 bg-white px-6 py-4">
      <div>
        <h1 className="text-[17px] font-semibold text-ink-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[12.5px] text-ink-500">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}
