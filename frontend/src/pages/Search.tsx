import clsx from "clsx";
import { Network, TextSearch } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../App";
import EvidenceExplorer from "./EvidenceExplorer";
import QueryWorkspace from "./QueryWorkspace";

/** One search page: "Smart search" over the knowledge graph, or plain text search over every passage. */
export default function SearchPage({ initial = "graph" }: { initial?: "graph" | "text" }) {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "graph" | "text") || initial;
  const tabs = [
    { id: "graph" as const, label: "Smart search", hint: "Understands drugs, diseases, tests and outcomes; answers from verified facts", icon: Network },
    { id: "text" as const, label: "Text search", hint: "Finds exact words in every protocol page", icon: TextSearch },
  ];
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Search" subtitle="Find trials by drug, disease, biomarker, outcome or exact wording. Switch on local AI to get the results explained in plain language." />
      <div className="flex gap-1 border-b border-ink-200 bg-white px-6">
        {tabs.map(({ id, label, hint, icon: Icon }) => (
          <button key={id} title={hint} onClick={() => setParams({ tab: id })} className={clsx("flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px] font-medium transition",
            tab === id ? "border-violet-600 text-violet-800" : "border-transparent text-ink-500 hover:text-ink-800")}><Icon className="h-4 w-4" />{label}</button>))}
      </div>
      <div className="min-h-0 flex-1">{tab === "graph" ? <QueryWorkspace embedded /> : <EvidenceExplorer embedded />}</div>
    </div>
  );
}
