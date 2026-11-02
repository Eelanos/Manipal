"use client";

import { useEffect, useMemo, useState } from "react";
import { useFilters } from "@/lib/filter-context";
import { fetchPredictOptions, fetchPredictOverview } from "@/lib/predict-api";
import type { PredictOptions, PredictOverview } from "@/lib/predict-types";
import CoverChart from "./CoverChart";
import ForecastChart from "./ForecastChart";
import HealthDonut from "./HealthDonut";
import ItemModal from "./ItemModal";
import NumbersHelp from "./NumbersHelp";
import PlanTable from "./PlanTable";
import PredictKpi from "./PredictKpi";
import StatusModal from "./StatusModal";
import { excessCompactCols, reorderCompactCols } from "./columns";
import { card } from "./shared";

type Tab = "reorder" | "excess";

export default function PredictPage() {
  const { filters: shared } = useFilters();
  // Period and Department are not shown on this page, so a value picked on another page must not
  // silently change these numbers: always plan for the whole selection of Unit + Product Group.
  const filters = useMemo(() => ({ ...shared, department: "All" }), [shared]);
  const [options, setOptions] = useState<PredictOptions | null>(null);
  const [optErr, setOptErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("reorder");
  const [statusPick, setStatusPick] = useState<string | null>(null);
  const [itemPick, setItemPick] = useState<{ item_id: string; unit_id: string } | null>(null);
  // The latest answer tagged with the request it belongs to; loading is derived from that.
  const [res, setRes] = useState<{ key: string; data: PredictOverview | null; error: string | null } | null>(null);

  useEffect(() => {
    fetchPredictOptions().then(setOptions).catch((e) => setOptErr(String(e.message ?? e)));
  }, []);

  const reqKey = useMemo(() => JSON.stringify(filters), [filters]);
  useEffect(() => {
    if (!options) return;
    const ac = new AbortController();
    fetchPredictOverview(filters, ac.signal)
      .then((d) => setRes({ key: reqKey, data: d, error: null }))
      .catch((e) => { if (e.name !== "AbortError") setRes({ key: reqKey, data: null, error: String(e.message ?? e) }); });
    return () => ac.abort();
  }, [options, filters, reqKey]);
  const data = res?.data ?? null;
  const error = res?.error ?? null;
  const loading = !res || res.key !== reqKey;

  const reorderCompact = useMemo(() => reorderCompactCols(setItemPick), []);
  const excessCompact = useMemo(() => excessCompactCols(setItemPick), []);

  if (optErr) return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">Could not load Predictive Analysis: {optErr}</div>;
  if (!options) return <div className="h-40 animate-pulse rounded-lg bg-slate-200" />;

  const s = data?.settings;
  // pb-20 below: lets the last card scroll clear of the floating chat button (it covered the table pager).
  return (
    <div className="space-y-5 pb-20">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">Predictive Analysis</h1>
        <p className="mt-0.5 text-sm font-medium text-slate-600">Demand &amp; Replenishment Planner</p>
        {s && (
          <p className="mt-1 text-xs text-slate-500">
            Assumes: {String(s.window_months)}-month usage · {String(s.lead_days)}d delivery · {String(s.buffer_days)}d buffer ·{" "}
            {String(s.plan_days)}d order cover
          </p>
        )}
      </header>

      {error && <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{error}</div>}
      {!data && loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">{[...Array(5)].map((_, i) => <div key={i} className="h-24 animate-pulse rounded-lg bg-slate-200" />)}</div>
          <div className="h-72 animate-pulse rounded-lg bg-slate-200" />
        </div>
      )}

      {data && (
        <div className={`space-y-5 transition-opacity ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
          {data.department_note && (
            <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm text-sky-900">
              Stock is not tracked by department: only the demand forecast follows the Department filter.
            </div>
          )}

          {data.empty ? (
            <div className="rounded-lg border border-slate-200 bg-white p-10 text-center">
              <p className="text-slate-600">No stock, usage or open orders for the selected filters.</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                {data.kpis.map((k) => <PredictKpi key={k.label} kpi={k} />)}
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
              {data.insights.length > 0 && (
                <div className="rounded-lg border border-slate-200 bg-white px-5 py-4 shadow-sm">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-100 text-amber-600" aria-hidden>
                      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                        <line x1="12" y1="9" x2="12" y2="13" />
                        <line x1="12" y1="17" x2="12.01" y2="17" />
                      </svg>
                    </span>
                    <p className="text-sm font-semibold uppercase tracking-wide text-slate-700">Needs attention</p>
                  </div>
                  <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-slate-800 marker:text-amber-500">
                    {data.insights.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                </div>
              )}
              <NumbersHelp notes={data.notes} />
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <ForecastChart f={data.forecast} />
                <HealthDonut slices={data.health} onPick={setStatusPick} />
                <CoverChart rows={data.cover.rows} leadDays={data.cover.lead_days} options={options} />
                <div className={`chart-card ${card}`}>
                  <div className="mb-3 inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
                    {([["reorder", `Suggested orders (${data.reorder.total.toLocaleString("en-IN")})`],
                       ["excess", `Excess stock (${data.excess.total.toLocaleString("en-IN")})`]] as [Tab, string][]).map(([k, t]) => (
                      <button key={k} type="button" aria-pressed={tab === k} onClick={() => setTab(k)}
                              className={`rounded px-3.5 py-1.5 font-medium ${tab === k ? "bg-nav text-white" : "text-slate-700 hover:bg-slate-100"}`}>{t}</button>
                    ))}
                  </div>
                  {tab === "reorder" ? (
                    <PlanTable key="reorder" rows={data.reorder.rows} cols={reorderCompact} onPick={setItemPick} pageSize={10}
                               total={data.reorder.total} more={data.reorder.more} emptyText="Nothing needs ordering right now." />
                  ) : (
                    <PlanTable key="excess" rows={data.excess.rows} cols={excessCompact} onPick={setItemPick} pageSize={10}
                               total={data.excess.total} more={data.excess.more} emptyText="No excess stock." />
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {statusPick && <StatusModal status={statusPick} filters={filters} options={options} onPick={setItemPick} onClose={() => setStatusPick(null)} />}
      {itemPick && <ItemModal target={itemPick} filters={filters} options={options} onClose={() => setItemPick(null)} />}
    </div>
  );
}
