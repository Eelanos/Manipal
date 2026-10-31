"use client";

import { fmtDelta, fmtValue } from "@/lib/rca-format";
import type { RcaLens, RcaOptions, TopCause } from "@/lib/rca-types";
import EntityCard from "./EntityCard";
import { PatternTag } from "./RcaParts";
import { btn, btnPrimary, Controls, type ControlsProps, Crumbs, ErrorBox, panel } from "./RcaShell";

function Kpi({ label, children, sub }: { label: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="kpi-card rounded-lg border border-slate-200 bg-white px-3.5 py-2 shadow-sm">
      <p className="truncate text-[10.5px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <div className="mt-0.5 text-[22px] font-extrabold leading-none tracking-tight text-slate-900">{children}</div>
      {sub && <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-500">{sub}</p>}
    </div>
  );
}

export interface CommandCenterProps {
  options: RcaOptions;
  controls: ControlsProps;
  lens: RcaLens | null;
  loading: boolean;
  error: string | null;
  causes: Record<string, TopCause | null>;
  onOpenEntity: (segment: string) => void;
  onExplorer: () => void;
  onTree: () => void;
  hasTree: boolean;
}

export default function CommandCenter(p: CommandCenterProps) {
  const { lens } = p;
  const cards = p.options.home_cards ?? 8;
  const m = lens?.metric;
  const fmt = m?.fmt ?? "percent";
  const flags = lens?.summary.flags;
  const flagged = lens ? lens.entities.filter((e) => e.flag === "deviating" && e.tone !== "good").length : 0;
  const unusualGood = lens ? lens.entities.filter((e) => e.flag === "deviating" && e.tone === "good").length : 0;
  const top = lens?.entities[0];
  const ev = lens?.evidence;
  const word = lens ? lens.lens.label.toLowerCase() : "";

  return (
    <div className="space-y-2.5">
      <Crumbs items={[{ label: "Command Center" }]}
              right={lens && (
                <>
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold text-red-700">
                    <i className="inline-block h-2 w-2 rounded-full bg-red-600" />{flagged} flagged {word}{flagged === 1 ? "" : "s"}
                  </span>
                  <button type="button" onClick={p.onExplorer} className={btnPrimary}>View all {lens.summary.count} {word}s →</button>
                </>
              )} />

      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[20px] font-semibold text-slate-900">Root Cause Analysis</h1>
        {lens && <p className="text-[13px] text-slate-500">
          {lens.metric.label} · {lens.period.label} vs {lens.compare.label} · {lens.summary.count} {word}s</p>}
      </div>

      <div className={`${panel} px-3.5 py-2.5`}><Controls {...p.controls} views={lens?.lenses ?? null} /></div>

      {p.error && <ErrorBox message={p.error} />}

      {!p.error && (
        <div className={`space-y-2.5 transition-opacity ${p.loading ? "opacity-50" : ""}`}>
          {!lens ? (
            <div className="h-72 animate-pulse rounded-lg bg-slate-200" />
          ) : lens.entities.length === 0 ? (
            <div className={`${panel} p-5 text-sm text-slate-600`}>
              There is only one {word} in the current top-bar filters, so there is nothing to compare. Pick another view above, or widen the Unit / Department filters.
            </div>
          ) : (
            <>
              <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-5">
                <Kpi label={`${lens.metric.label} · ${lens.period.label}`}
                     sub={<><span className={lens.headline.tone === "bad" ? "font-semibold text-red-700" : lens.headline.tone === "good" ? "font-semibold text-emerald-700" : "font-semibold text-slate-700"}>
                       {lens.headline.flat ? "■ flat" : lens.headline.delta < 0 ? "▼" : "▲"} {fmtDelta(fmt, lens.headline.delta)}</span> vs {lens.compare.label} ({fmtValue(fmt, lens.headline.base)})</>}>
                  {fmtValue(fmt, lens.headline.current)}
                </Kpi>
                <Kpi label={`${lens.lens.label}s flagged`}
                     sub={`High attention (unusual and material); ${flags?.watch ?? 0} more to watch${unusualGood ? `, ${unusualGood} unusually better` : ""}`}>
                  <span className={flagged ? "text-red-700" : ""}>{flagged}</span><span className="text-base font-semibold text-slate-400"> of {lens.summary.count}</span>
                </Kpi>
                <Kpi label="Biggest mover" sub={top ? <>{fmtDelta(fmt, top.contribution)}{top.share_pct != null && top.share_pct > 0 && !lens.headline.flat ? ` · ${top.share_pct.toFixed(0)}% of the change` : ""}</> : ""}>
                  <span className="block truncate text-[20px]" title={top?.segment}>{top?.segment ?? "–"}</span>
                </Kpi>
                <Kpi label="Top 3 explain"
                     sub={<><PatternTag p={lens.summary.pattern} />{lens.summary.offsets && <span className="ml-1.5">others offset</span>}</>}>
                  {lens.summary.top3_share_pct != null ? `${lens.summary.top3_share_pct.toFixed(0)}%` : "–"}
                </Kpi>
                <Kpi label="Is the month unusual?"
                     sub={ev?.available ? `${Math.abs(ev.z ?? 0).toFixed(1)} std. dev. ${(ev.z ?? 0) >= 0 ? "above" : "below"} normal, vs ${ev.n} other months` : ev?.reason}>
                  <span className={ev?.flag === "unusual" ? "text-red-700" : ev?.flag === "watch" ? "text-amber-700" : ""}>
                    {ev?.available ? (ev.flag === "unusual" ? "Unusual" : ev.flag === "watch" ? "Watch" : "Normal") : "Unknown"}</span>
                </Kpi>
              </div>

              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  {lens.lens.label} overview — click any card to explore
                  {lens.entities.length > cards && <span className="ml-2 normal-case tracking-normal text-slate-400">the {cards} that hurt the number most come first · {lens.entities.length - cards} more in “View all”</span>}
                </p>
                <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
                  {lens.entities.slice(0, cards).map((e) => (
                    <EntityCard key={e.segment} e={e} lens={lens} cause={p.causes[e.segment]} onOpen={() => p.onOpenEntity(e.segment)} />
                  ))}
                </div>
              </div>

              <div className={`${panel} flex flex-wrap items-center gap-x-6 gap-y-2 py-2 pl-3.5 pr-20 text-[12px] text-slate-700`}>
                <p className="min-w-0 flex-1 line-clamp-2 leading-snug" title={lens.narrative.join(" ")}>{lens.narrative[0]}</p>
                <span className="text-emerald-700" title={lens.reconciliation.checked}>
                  {lens.reconciliation.ok ? "✔ Every figure adds up exactly" : "⚠ Check needed: parts do not add up"}</span>
                {p.hasTree && <button type="button" onClick={p.onTree} className={btn}>KPI tree →</button>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
