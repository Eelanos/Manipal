"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchRcaAnalysis, fetchRcaEntity } from "@/lib/rca-api";
import { fmtDelta, fmtValue } from "@/lib/rca-format";
import type { FilterState } from "@/lib/types";
import type { RcaAnalysis, RcaEntityView, RcaOptions } from "@/lib/rca-types";
import ImpactBars from "./ImpactBars";
import RcaEvidenceChart from "./RcaEvidenceChart";
import { btn, btnPrimary, Crumbs, ErrorBox, Modal, panel, StatusBadge } from "./RcaShell";
import { shareText } from "./EntityCard";

interface Params { metric: string; month: string; compare: string }

function Kpi({ label, tone, children, sub, onClick }: { label: string; tone?: string; children: React.ReactNode; sub?: React.ReactNode; onClick?: () => void }) {
  const color = tone === "bad" ? "text-red-700" : tone === "good" ? "text-emerald-700" : tone === "accent" ? "text-accent" : "text-slate-900";
  return (
    <div className={`kpi-card rounded-lg border border-slate-200 bg-white px-3.5 py-2 shadow-sm ${onClick ? "cursor-pointer hover:bg-slate-50" : ""}`} onClick={onClick}>
      <p className="truncate text-[10.5px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-0.5 text-[22px] font-extrabold leading-none tracking-tight ${color}`}>{children}</p>
      {sub && <p className="mt-1 truncate text-[11px] leading-snug text-slate-500">{sub}</p>}
    </div>
  );
}

export default function EntityDetail({
  options, params, filters, dim, segment, hasTree, onHome, onExplorer, onDrill, onTree,
}: {
  options: RcaOptions; params: Params; filters: FilterState; dim: string; segment: string; hasTree: boolean;
  onHome: () => void; onExplorer: () => void;
  onDrill: (path: string[]) => void; onTree: (path: string[]) => void;
}) {
  const [pickDim, setPickDim] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  // The result is stored together with the request it answers, so nothing from an earlier entity is ever shown
  // (state is only set when a response arrives, never at the start of the effect).
  const reqKey = [params.metric, params.month, params.compare, JSON.stringify(filters), dim, segment].join("#");
  const [res, setRes] = useState<{ key: string; view: RcaEntityView | null; an: RcaAnalysis | null; err: string | null } | null>(null);
  const cur = res?.key === reqKey ? res : null;
  const view = cur?.view ?? null;
  const an = cur?.an ?? null;
  const err = cur?.err ?? null;

  // A different entity or period starts with no picked view (adjusted while rendering, not in an effect).
  const [seenKey, setSeenKey] = useState(reqKey);
  if (seenKey !== reqKey) { setSeenKey(reqKey); setPickDim(null); }

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([
      fetchRcaEntity(params, filters, dim, segment, ac.signal),
      fetchRcaAnalysis(params, filters, [`${dim}:${segment}`], ac.signal),
    ]).then(([v, a]) => setRes({ key: reqKey, view: v, an: a, err: null }))
      .catch((e) => { if (e.name !== "AbortError") setRes({ key: reqKey, view: null, an: null, err: String(e.message ?? e) }); });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqKey]);

  // Dimensions ordered by how sharply they concentrate this entity's change (share of its own change).
  const dims = useMemo(() => {
    if (!an) return [];
    const best = (d: RcaAnalysis["dimensions"][number]) => Math.max(...d.rows.map((r) => r.share_of_slice_pct ?? -1), -1);
    return [...an.dimensions].sort((a, b) => best(b) - best(a));
  }, [an]);
  const shown = dims.find((d) => d.key === pickDim) ?? dims.find((d) => d.key === view?.ranking[0]?.dim) ?? dims[0];

  const crumbs = [
    { label: "Home", onClick: onHome }, { label: "Findings", onClick: onExplorer },
    { label: `${segment}` },
  ];
  if (err) return <div className="space-y-3"><Crumbs items={crumbs} /><ErrorBox message={err} onBack={onExplorer} /></div>;
  if (!view || !an) return <div className="space-y-3"><Crumbs items={crumbs} /><div className="h-96 animate-pulse rounded-lg bg-slate-200" /></div>;

  const { entity: e, metric: m } = view;
  const fmt = m.fmt;
  const meta = options.thresholds;
  const ev = e.evidence;
  const path = [`${dim}:${segment}`];

  return (
    <div className="flex h-[calc(100vh-128px)] min-h-[34rem] flex-col gap-2.5">
      <Crumbs items={crumbs} />

      <div className={`${panel} flex flex-wrap items-center gap-3 px-4 py-2.5`}>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[20px] font-semibold leading-tight text-slate-900">{segment}</h1>
          <p className="text-[13px] text-slate-500">{e.dim_label} · {view.period.label} · {m.label} vs {view.compare.label}</p>
        </div>
        <StatusBadge flag={e.flag} tone={e.tone} className="text-[11.5px]" />
        <span className={`rounded px-2 py-0.5 text-[10.5px] font-bold tracking-wide ring-1 ring-inset ${view.reconciliation.ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-red-50 text-red-800 ring-red-200"}`}
              title={view.reconciliation.checked}>{view.reconciliation.ok ? "✔ ADDS UP" : "⚠ CHECK"}</span>
        <div className="flex items-center gap-2">
          <button type="button" className={btn} onClick={onExplorer}>← Findings</button>
          <button type="button" className={btnPrimary} onClick={() => onDrill(path)}>Drill-down →</button>
          <button type="button" className={btnPrimary} disabled={!hasTree} onClick={() => onTree(path)}
                  title={hasTree ? undefined : "KPI trees exist for Formulary compliance and Inventory days"}>KPI tree →</button>
        </div>
      </div>

      <div className="grid shrink-0 gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label={`${m.label} now`} sub={`${view.compare.label}: ${fmtValue(fmt, e.own_base)}`}>{fmtValue(fmt, e.own_current)}</Kpi>
        <Kpi label="Its own change" tone={e.own_change == null ? undefined : e.tone}
             sub={`versus ${view.compare.label.toLowerCase()}`}>{fmtDelta(fmt, e.own_change)}</Kpi>
        <Kpi label="Part of the total change" tone={e.tone}
             sub={shareText(e.share_pct, view.headline.flat) || `of ${fmtDelta(fmt, view.headline.delta)}`}>{fmtDelta(fmt, e.contribution)}</Kpi>
        <Kpi label="Unusual for itself?" tone={ev.flag === "unusual" ? "bad" : undefined} onClick={ev.available ? () => setShowHistory(true) : undefined}
             sub={ev.available ? <>{Math.abs(ev.z ?? 0).toFixed(1)} std. dev. {(ev.z ?? 0) >= 0 ? "above" : "below"} its usual · <span className="text-accent underline">see history</span></> : ev.reason}>
          {ev.available ? (ev.flag === "unusual" ? "Yes" : ev.flag === "watch" ? "Somewhat" : "No") : "Unknown"}
        </Kpi>
      </div>

      <div className="grid min-h-0 flex-1 gap-2.5 xl:grid-cols-2">
        <div className={`${panel} min-h-0 overflow-auto p-4`}>
          <h2 className="text-[15px] font-semibold text-slate-900">Root-cause ranking — top {Math.max(view.ranking.length, 0) || 5}</h2>
          <p className="text-[12px] text-slate-500">Where inside {segment} the change sits, across every view. Click one to drill into it.</p>
          {view.ranking.length === 0 ? (
            <>
              <p className="mt-3 rounded bg-slate-50 p-3 text-[13px] text-slate-600">
                No segment stands out beyond its own size, so the change inside {segment} is spread out. The impact chart shows how it splits.
              </p>
              {ev.available && (
                <div className="mt-3">
                  <p className="text-[12px] font-semibold text-slate-700">Is it normal for {segment}? Its own history, with the usual range shaded</p>
                  <RcaEvidenceChart ev={ev} fmt={fmt} />
                </div>
              )}
            </>
          ) : (
            <ol className="mt-2.5 space-y-2.5">
              {view.ranking.map((r, i) => (
                <li key={`${r.dim}:${r.segment}`}>
                  <button type="button" className="block w-full text-left" onClick={() => onDrill([...path, `${r.dim}:${r.segment}`])}>
                    <div className="flex items-baseline gap-2">
                      <span className="text-[12px] font-bold text-accent">#{i + 1}</span>
                      <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-slate-900">{r.segment}</span>
                      <span className="text-[13px] font-semibold tabular-nums text-slate-700">{r.share_of_slice_pct.toFixed(0)}%</span>
                    </div>
                    <div className="relative mt-1 h-2 rounded bg-slate-100">
                      <div className="h-2 rounded bg-accent" style={{ width: `${Math.min(100, r.share_of_slice_pct)}%` }} />
                      {r.weight_in_slice_pct != null && (
                        <i className="absolute -top-0.5 h-3 w-0.5 bg-slate-700" style={{ left: `${Math.min(100, r.weight_in_slice_pct)}%` }}
                           title={`Its share of ${segment}'s base: ${r.weight_in_slice_pct.toFixed(0)}%`} />
                      )}
                    </div>
                    <p className="mt-1 text-[11.5px] text-slate-500">
                      <span className="mr-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-600">{r.dim_label}</span>
                      {fmtDelta(fmt, r.contribution)} · {r.share_of_slice_pct.toFixed(0)}% of its change
                      {r.weight_in_slice_pct != null ? ` vs ${r.weight_in_slice_pct.toFixed(0)}% of its base (the tick)` : ""}
                    </p>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className={`${panel} min-h-0 overflow-auto p-4`}>
          <h2 className="text-[15px] font-semibold text-slate-900">Impact by {shown ? shown.label.toLowerCase() : "view"}</h2>
          <p className="text-[12px] text-slate-500">Each segment’s part of {segment}’s change. Pick another view:</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {dims.slice(0, 7).map((d) => (
              <button key={d.key} type="button" aria-pressed={shown?.key === d.key} onClick={() => setPickDim(d.key)}
                      className={`rounded-full border px-2.5 py-0.5 text-[12px] font-medium ${shown?.key === d.key ? "border-nav bg-nav text-white" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>{d.label}</button>
            ))}
            {dims.length > 7 && (
              <select aria-label="More views" value={dims.slice(7).some((d) => d.key === shown?.key) ? shown?.key : ""} onChange={(ev2) => ev2.target.value && setPickDim(ev2.target.value)}
                      className="rounded-full border border-slate-300 bg-white px-2.5 py-0.5 text-[12px]">
                <option value="">More…</option>
                {dims.slice(7).map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
              </select>
            )}
          </div>
          <div className="mt-2">
            {shown ? <ImpactBars dim={shown} fmt={fmt} higherIs={m.higher_is} total={shown.slice_total ?? an.slice_total ?? null}
                                 onPick={(seg) => onDrill([...path, `${shown.key}:${seg}`])} />
                   : <p className="text-sm text-slate-500">Nothing to split.</p>}
          </div>
        </div>
      </div>

      <div className="shrink-0 rounded-lg border border-slate-200 bg-slate-50 py-2.5 pl-4 pr-20">
        <h2 className="text-[13px] font-semibold text-slate-900">What the data says</h2>
        <ul className="mt-1 grid gap-x-8 gap-y-0.5 text-[12.5px] leading-snug text-slate-700 lg:grid-cols-2">
          {view.narrative.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
        <p className="mt-1.5 text-[11px] text-slate-500"><b>Why it moved is not proven here.</b> The data shows where the change sits and whether it is unusual; confirm the cause with the team that runs {segment}.{meta ? ` HIGH = at least ${meta.material_share_pct}% of all movement and over ${meta.z_unusual} std. dev. from its own normal.` : ""}</p>
      </div>

      {showHistory && (
        <Modal title={`${segment}: is it a real change or normal wobble?`} onClose={() => setShowHistory(false)}>
          <p className="mb-2 text-[12px] text-slate-500">{m.label}: {ev.basis === "level" ? "its own level in every month" : `its own ${ev.basis} in every month`}, with the usual range shaded.</p>
          <RcaEvidenceChart ev={ev} fmt={fmt} />
        </Modal>
      )}
    </div>
  );
}
