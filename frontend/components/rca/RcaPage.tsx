"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchRcaAnalysis, fetchRcaOptions, fetchRcaTree } from "@/lib/rca-api";
import { useFilters } from "@/lib/filter-context";
import type { RcaAnalysis, RcaOptions, RcaTree } from "@/lib/rca-types";
import RcaEvidenceChart from "./RcaEvidenceChart";
import { DimensionOverview, DimensionTable, DrillChain, Headline, card, h2, sub } from "./RcaParts";
import RcaTreeView from "./RcaTreeView";
import RcaWaterfall from "./RcaWaterfall";

type Tab = "drivers" | "tree";
const sel = "w-full rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700 focus:border-accent focus:outline-none disabled:opacity-50";
const lbl = "mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500";

export default function RcaPage() {
  const { filters } = useFilters();
  const [options, setOptions] = useState<RcaOptions | null>(null);
  const [optErr, setOptErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("drivers");
  const [metric, setMetric] = useState("");
  const [month, setMonth] = useState("");
  const [compare, setCompare] = useState("prior_month");
  const [path, setPath] = useState<string[]>([]);
  const [dimKey, setDimKey] = useState<string | null>(null);

  const [data, setData] = useState<RcaAnalysis | null>(null);
  const [tree, setTree] = useState<RcaTree | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRcaOptions().then((o) => {
      setOptions(o);
      setMetric(o.metrics[0].key);
      setMonth(o.default_month);
      setCompare(o.metrics[0].compares[0].key);
    }).catch((e) => setOptErr(String(e.message ?? e)));
  }, []);

  const m = options?.metrics.find((x) => x.key === metric);
  const monthInfo = options?.months.find((x) => x.value === month);
  const compareOk = (key: string) =>
    key === "prior_month" ? monthInfo?.has_prior_month !== false
    : key === "same_month_last_year" ? monthInfo?.has_same_month_last_year !== false : true;
  // The tree only offers month-on-month style comparisons.
  const compares = (tab === "tree" ? m?.compares.filter((c) => m.tree_compares.includes(c.key)) : m?.compares) ?? [];

  // Keep the comparison valid when the metric, month or tab changes.
  useEffect(() => {
    if (!m) return;
    const allowed = compares.filter((c) => compareOk(c.key));
    if (allowed.length && !allowed.some((c) => c.key === compare)) setCompare(allowed[0].key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metric, month, tab, options]);

  useEffect(() => { setPath([]); setDimKey(null); }, [metric, month, compare, filters]);

  // The tree exists for some metrics only; switching to it moves to one that has a tree.
  useEffect(() => {
    if (tab === "tree" && options && m && !m.has_tree) {
      const t = options.metrics.find((x) => x.has_tree);
      if (t) setMetric(t.key);
    }
  }, [tab, options, m]);

  // Load the analysis. Any control or top-bar filter change restarts the drill path.
  const pathKey = path.join("|");
  useEffect(() => {
    if (!options || !metric || !month || !m) return;
    if (!compares.some((c) => c.key === compare)) return;
    if (tab === "tree" && !m.has_tree) return;
    const ac = new AbortController();
    setLoading(true); setError(null);
    const p = { metric, month, compare };
    const job = tab === "drivers"
      ? fetchRcaAnalysis(p, filters, path, ac.signal).then((d) => { setData(d); })
      : fetchRcaTree(p, filters, ac.signal).then((d) => { setTree(d); });
    job.catch((e) => { if (e.name !== "AbortError") setError(String(e.message ?? e)); })
       .finally(() => { if (!ac.signal.aborted) setLoading(false); });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, metric, month, compare, tab, filters, pathKey]);

  // Which dimension is shown as a waterfall: the user's pick, else the most concentrated one.
  const dim = useMemo(() => {
    if (!data) return null;
    return data.dimensions.find((d) => d.key === dimKey)
      ?? data.dimensions.find((d) => d.key === data.suggestion?.dim) ?? data.dimensions[0] ?? null;
  }, [data, dimKey]);

  const drill = (d: string, seg: string) => { setPath((p) => [...p, `${d}:${seg}`]); setDimKey(null); };

  if (optErr) return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">Could not load the RCA options: {optErr}</div>;
  if (!options || !m) return <div className="h-40 animate-pulse rounded-lg bg-slate-200" />;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">Root Cause Analysis</h1>
        <div className="ml-auto inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
          {([["drivers", "Driver analysis"], ["tree", "KPI tree"]] as [Tab, string][]).map(([k, t]) => (
            <button key={k} type="button" onClick={() => setTab(k)} aria-pressed={tab === k}
                    className={`rounded px-3.5 py-1.5 font-medium ${tab === k ? "bg-nav text-white" : "text-slate-700 hover:bg-slate-100"}`}>{t}</button>
          ))}
        </div>
      </header>

      <div className={card}>
        <div className="grid gap-4 md:grid-cols-3">
          <div><label className={lbl}>Metric</label>
            <select className={sel} value={metric} onChange={(e) => { setMetric(e.target.value); setCompare(options.metrics.find((x) => x.key === e.target.value)!.compares[0].key); }}>
              {options.metrics.filter((x) => tab === "drivers" || x.has_tree).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
            </select></div>
          <div><label className={lbl}>Month to explain</label>
            <select className={sel} value={month} onChange={(e) => setMonth(e.target.value)}>
              {[...options.months].reverse().map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
            </select></div>
          <div><label className={lbl}>Compare against</label>
            <select className={sel} value={compare} onChange={(e) => setCompare(e.target.value)}>
              {compares.map((c) => <option key={c.key} value={c.key} disabled={!compareOk(c.key)}>{c.label}{compareOk(c.key) ? "" : " (no data)"}</option>)}
            </select></div>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
          {m.definition} The Unit, Stock Take Group and Department filters in the top bar apply; the Period filter does not, because RCA explains one month.
        </p>
      </div>

      {tab === "tree" && !m.has_tree && (
        <div className={`${card} text-sm text-slate-600`}>No KPI tree is defined for {m.label}. Trees exist for Formulary compliance and Inventory days.</div>
      )}

      {error && <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{error}</div>}
      {loading && <div className="h-48 animate-pulse rounded-lg bg-slate-200" />}

      {!loading && !error && tab === "drivers" && data && (
        <>
          <Headline data={data} />
          <DrillChain data={data} onStepUp={() => setPath((p) => p.slice(0, -1))} onReset={() => setPath([])} onDrill={drill} />
          {dim && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <div className={card}>
                <h2 className={h2}>What moved the number, by {dim.label.toLowerCase()}</h2>
                <p className={sub}>{data.compare.label} → {data.period.label}. Each bar is that segment’s part of the change.</p>
                <div className="mt-2"><RcaWaterfall data={data} dim={dim} onDrill={drill} /></div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-600">
                  {data.metric.higher_is === "neutral"
                    ? <><span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm align-[-1px]" style={{ background: "#2f54d4" }} />Pushed it up</span>
                        <span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm align-[-1px]" style={{ background: "#e08a1e" }} />Pulled it down</span></>
                    : <><span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm align-[-1px]" style={{ background: "#a4262c" }} />Moved it the wrong way</span>
                        <span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm align-[-1px]" style={{ background: "#2a9d8f" }} />Moved it the right way</span></>}
                  <span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm align-[-1px]" style={{ background: "#3b4559" }} />Level</span>
                </div>
              </div>
              <DimensionOverview data={data} selected={dim.key} onSelect={setDimKey} />
            </div>
          )}
          {dim && <DimensionTable data={data} dim={dim} onDrill={drill} />}
          <div className={card}>
            <h2 className={h2}>Is it a real change or normal wobble?</h2>
            <p className={sub}>{data.metric.label}: {data.evidence.basis === "level" ? "its level in every month" : `its ${data.evidence.basis} in every month`}, with the usual range shaded.</p>
            <div className="mt-2 max-w-3xl"><RcaEvidenceChart ev={data.evidence} fmt={data.metric.fmt} /></div>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-950">
            <b>How to read this.</b> Every number is calculated from the transactions and the splits add up exactly to the change; nothing is estimated and no AI writes the figures.
            A segment that carries most of a change is where to look, not proof of why it happened. Large segments (a big unit, a big department) lead more often simply because they are large:
            compare “Impact” with the segment’s size and its own history before concluding. “Unusual” compares a month with the same measure in the other months of the data, nothing more.
          </div>
        </>
      )}

      {!loading && !error && tab === "tree" && tree && m.has_tree && <RcaTreeView key={`${metric}|${month}|${compare}`} data={tree} />}
    </div>
  );
}
