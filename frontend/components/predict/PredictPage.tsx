"use client";

import { useEffect, useMemo, useState } from "react";
import { useFilters } from "@/lib/filter-context";
import { fetchPredictOptions, fetchPredictOverview } from "@/lib/predict-api";
import type { PredictOptions, PredictOverview } from "@/lib/predict-types";
import CoverChart from "./CoverChart";
import ForecastChart from "./ForecastChart";
import HealthDonut from "./HealthDonut";
import ItemModal from "./ItemModal";
import PlanTable from "./PlanTable";
import PredictKpi from "./PredictKpi";
import StatusModal from "./StatusModal";
import { excessCols, reorderCols } from "./columns";
import { card, dateText, h2, sub } from "./shared";

type Tab = "reorder" | "excess";

export default function PredictPage() {
  const { filters } = useFilters();
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

  const reorder = useMemo(() => reorderCols(options), [options]);
  const excess = useMemo(() => excessCols(options), [options]);

  if (optErr) return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">Could not load Predictive Analysis: {optErr}</div>;
  if (!options) return <div className="h-40 animate-pulse rounded-lg bg-slate-200" />;

  const s = data?.settings;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">Demand &amp; Replenishment Planner</h1>
        <p className={sub}>
          What to order, how much and when. Stock as of {dateText(data?.as_of ?? options.as_of)}.
        </p>
        {s && (
          <p className="mt-1 text-xs text-slate-500">
            Assumes: {String(s.window_months)}-month usage · {String(s.lead_days)}d delivery · {String(s.buffer_days)}d buffer ·
            {String(s.plan_days)}d order cover · excess above {String(s.max_cover_days)}d of usage
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
              {data.insights.length > 0 && (
                <div className="rounded-lg border border-slate-200 bg-white px-5 py-4 shadow-sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Needs attention</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-800">
                    {data.insights.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                </div>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <ForecastChart f={data.forecast} />
                <HealthDonut slices={data.health} onPick={setStatusPick} />
                <CoverChart rows={data.cover.rows} leadDays={data.cover.lead_days} options={options} />
                <div className={card}>
                  <h2 className={h2}>How the numbers are worked out</h2>
                  <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
                    <li><b>Daily usage</b> = quantity used in the period ÷ days in it.</li>
                    <li><b>Days of cover</b> = how many days current stock lasts at that usage.</li>
                    <li><b>Reorder point</b> = usage over the delivery time + safety buffer.</li>
                    <li><b>Order quantity</b> = usage over delivery + buffer + order-cover days, minus stock and open orders.</li>
                    <li><b>Excess</b> = stock above the maximum days of usage.</li>
                    <li><b>Seasonality</b> = busy months (for example December) are scaled up and quiet ones down, using the same month in earlier years.</li>
                  </ul>
                  <ul className="mt-3 space-y-0.5 border-t border-slate-100 pt-2 text-[11px] leading-snug text-slate-500">
                    {data.notes.map((n, i) => <li key={i}>{n}</li>)}
                  </ul>
                </div>
              </div>

              <div className={`chart-card ${card}`}>
                <div className="mb-3 inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
                  {([["reorder", `Suggested orders (${data.reorder.total.toLocaleString("en-IN")})`],
                     ["excess", `Excess stock (${data.excess.total.toLocaleString("en-IN")})`]] as [Tab, string][]).map(([k, t]) => (
                    <button key={k} type="button" aria-pressed={tab === k} onClick={() => setTab(k)}
                            className={`rounded px-3.5 py-1.5 font-medium ${tab === k ? "bg-nav text-white" : "text-slate-700 hover:bg-slate-100"}`}>{t}</button>
                  ))}
                </div>
                {tab === "reorder" ? (
                  <PlanTable key="reorder" rows={data.reorder.rows} cols={reorder} onPick={setItemPick}
                             total={data.reorder.total} more={data.reorder.more} emptyText="Nothing needs ordering right now." />
                ) : (
                  <PlanTable key="excess" rows={data.excess.rows} cols={excess} onPick={setItemPick}
                             total={data.excess.total} more={data.excess.more} emptyText="No excess stock." />
                )}
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
