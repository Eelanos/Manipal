"use client";

import { useEffect, useState } from "react";
import { fetchRcaTree } from "@/lib/rca-api";
import type { FilterState } from "@/lib/types";
import type { RcaOptions, RcaTree } from "@/lib/rca-types";
import RcaTreeView from "./RcaTreeView";
import { btn, Crumbs, ErrorBox, Segmented } from "./RcaShell";

interface Params { metric: string; month: string; compare: string }

// "How is the KPI built, and which branch moved?" - for the whole scope, or for one entity on its own.
export default function TreeScreen({
  options, params, filters, path, onHome, onBack,
}: { options: RcaOptions; params: Params; filters: FilterState; path: string[]; onHome: () => void; onBack: () => void }) {
  const metric = options.metrics.find((x) => x.key === params.metric)!;
  const allowed = metric.compares.filter((c) => metric.tree_compares.includes(c.key));
  // A tree compares two months; if the page is set to budget/target, use the first month comparison instead.
  const [compare, setCompare] = useState(allowed.some((c) => c.key === params.compare) ? params.compare : allowed[0]?.key ?? "prior_month");
  const [tree, setTree] = useState<RcaTree | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setTree(null); setErr(null);
    fetchRcaTree({ ...params, compare }, filters, ac.signal, path)
      .then(setTree)
      .catch((e) => { if (e.name !== "AbortError") setErr(String(e.message ?? e)); });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.metric, params.month, compare, filters, path.join("|")]);

  const who = path.map((p) => p.split(":")[1]).join(" › ");
  return (
    <div className="flex h-[calc(100vh-128px)] min-h-[34rem] flex-col gap-2.5">
      <Crumbs items={[{ label: "Home", onClick: onHome }, { label: "Back", onClick: onBack }, { label: "KPI tree" }]} />
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-semibold leading-tight text-slate-900">KPI tree{who ? `: ${who}` : ""}</h1>
          <p className="text-[13px] text-slate-500">
            {who ? `${who} on its own: its own ${metric.label.toLowerCase()} and the branches it is built from.` : `How ${metric.label.toLowerCase()} is built, and which branch moved.`}
          </p>
        </div>
        {allowed.length > 1 && (
          <Segmented inline label="Compare" value={compare} onChange={setCompare}
                     options={allowed.map((c) => ({ key: c.key, label: c.label }))} />
        )}
        <button type="button" className={btn} onClick={onBack}>← Back</button>
      </div>
      {err && <ErrorBox message={err} onBack={onBack} />}
      {!err && !tree && <div className="h-72 animate-pulse rounded-lg bg-slate-200" />}
      {tree && <div className="min-h-0 flex-1 overflow-y-auto"><RcaTreeView key={`${params.metric}|${params.month}|${compare}|${path.join("|")}`} data={tree} /></div>}
    </div>
  );
}
