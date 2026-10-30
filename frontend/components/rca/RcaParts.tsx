"use client";

import { fmtDelta, fmtValue } from "@/lib/rca-format";
import type { RcaAnalysis, RcaDimension, RcaEvidence } from "@/lib/rca-types";

export const card = "rounded-lg border border-slate-200 bg-white p-5 shadow-sm";
export const h2 = "text-sm font-semibold text-slate-900";
export const sub = "mt-0.5 text-xs text-slate-500";

const FLAG_STYLE: Record<string, string> = {
  unusual: "bg-red-50 text-red-800 ring-red-200",
  watch: "bg-amber-50 text-amber-800 ring-amber-200",
  normal: "bg-slate-100 text-slate-600 ring-slate-200",
  none: "bg-slate-50 text-slate-400 ring-slate-200",
};
const FLAG_TEXT: Record<string, string> = {
  unusual: "Unusual", watch: "Worth a look", normal: "Normal range", none: "No verdict",
};

export function EvidenceChip({ ev }: { ev: RcaEvidence }) {
  const k = ev.available && ev.flag ? ev.flag : "none";
  const title = ev.available
    ? `${ev.basis}: ${Math.abs(ev.z ?? 0).toFixed(1)} standard deviations ${((ev.z ?? 0) >= 0) ? "above" : "below"} its usual, over ${ev.n} other months`
    : ev.reason ?? "Not enough history";
  return (
    <span title={title}
          className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${FLAG_STYLE[k]}`}>
      {FLAG_TEXT[k]}
    </span>
  );
}

export function PatternTag({ p }: { p: string | null }) {
  if (!p) return <span className="text-slate-400">–</span>;
  const cls = p === "Concentrated" ? "bg-red-50 text-red-800 ring-red-200"
    : p === "Moderate" ? "bg-amber-50 text-amber-800 ring-amber-200" : "bg-slate-100 text-slate-600 ring-slate-200";
  return <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${cls}`}>{p}</span>;
}

function toneClass(t: string) {
  return t === "bad" ? "text-red-700" : t === "good" ? "text-emerald-700" : "text-slate-900";
}

// ---- Headline ---------------------------------------------------------------
export function Headline({ data }: { data: RcaAnalysis }) {
  const m = data.metric, h = data.headline, ev = data.evidence;
  const unusual = ev.available ? ev.flag : null;
  return (
    <div className={`${card} grid gap-6 lg:grid-cols-[18rem_1fr]`}>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{m.label} · {data.period.label}</p>
        <p className="mt-2 text-5xl font-extrabold tracking-tight text-slate-900">{fmtValue(m.fmt, h.current)}</p>
        <p className={`mt-2 text-sm font-semibold ${toneClass(h.tone)}`}>
          {h.flat ? "■ flat" : h.delta < 0 ? "▼" : "▲"} {fmtDelta(m.fmt, h.delta)}
          {h.delta_pct != null ? ` (${h.delta_pct >= 0 ? "+" : "−"}${Math.abs(h.delta_pct).toFixed(1)}%)` : ""}
          {" "}vs {data.compare.label}
        </p>
        <p className="mt-1 text-xs text-slate-500">{data.compare.label}: {fmtValue(m.fmt, h.base)}</p>
      </div>
      <div>
        <ul className="space-y-1.5 text-[15px] leading-relaxed text-slate-800">
          {data.narrative.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            <p className="mb-1 text-[13px] font-semibold text-slate-800">
              WHERE it moved · {data.reconciliation.ok ? "Exact" : "Check needed"}
            </p>
            {data.reconciliation.ok
              ? "Calculated from the transactions. Every split adds up to the full change; nothing is estimated."
              : `The splits differ from the total by ${data.reconciliation.max_gap}. Do not rely on this view.`}
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            <p className="mb-1 text-[13px] font-semibold text-slate-800">
              Is it unusual? · {unusual === "unusual" ? "Yes" : unusual === "watch" ? "Somewhat" : unusual === "normal" ? "No" : "Unknown"}
            </p>
            {ev.available
              ? `${Math.abs(ev.z ?? 0).toFixed(1)} standard deviations ${(ev.z ?? 0) >= 0 ? "above" : "below"} normal, compared with ${ev.n} other months.`
              : ev.reason}
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            <p className="mb-1 text-[13px] font-semibold text-slate-800">WHY it moved · Needs a human check</p>
            This shows where the change came from. It does not prove the cause; confirm it with the team that runs the area.
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Drill chain ------------------------------------------------------------
export function DrillChain({
  data, onStepUp, onReset, onDrill,
}: { data: RcaAnalysis; onStepUp: () => void; onReset: () => void; onDrill: (dim: string, seg: string) => void }) {
  const fmt = data.metric.fmt, s = data.suggestion;
  return (
    <div className={card}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className={h2}>Drill chain</h2>
          <p className={sub}>Each step narrows to one segment and explains its part of the original change.</p></div>
        {data.chain.length > 1 && (
          <div className="flex gap-2">
            <button type="button" onClick={onStepUp} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">Step up</button>
            <button type="button" onClick={onReset} className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">Reset</button>
          </div>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-stretch gap-2">
        {data.chain.map((c, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className={`min-w-[10rem] rounded-md border px-3 py-2 ${i === data.chain.length - 1 ? "border-brand bg-red-50/40" : "border-slate-200 bg-slate-50"}`}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{i === 0 ? "Whole scope" : `Step ${i}`}</p>
              <p className="text-[13px] font-semibold text-slate-900">{c.label}</p>
              <p className="text-sm font-bold text-slate-900">{fmtDelta(fmt, c.contribution)}</p>
              {c.share_pct != null && i > 0 && <p className="text-xs font-semibold text-brand">{c.share_pct.toFixed(0)}% of the change{c.share_pct > 100 ? " (others offset)" : ""}</p>}
            </div>
            {i < data.chain.length - 1 && <span className="text-xl text-slate-400">›</span>}
          </div>
        ))}
      </div>
      {s && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-md bg-canvas px-3 py-2 text-xs text-slate-700">
          <span>Biggest single concentration: <b>{s.segment}</b> ({s.dim_label.toLowerCase()}), {s.share_pct.toFixed(0)}% of the change.</span>
          <button type="button" onClick={() => onDrill(s.dim, s.segment)}
                  className="rounded-md bg-brand px-3 py-1 font-semibold text-white hover:bg-brand-dark">Drill into {s.segment}</button>
        </div>
      )}
    </div>
  );
}

// ---- Overview of all dimensions ---------------------------------------------
export function DimensionOverview({
  data, selected, onSelect,
}: { data: RcaAnalysis; selected: string; onSelect: (k: string) => void }) {
  const fmt = data.metric.fmt;
  const sorted = [...data.dimensions].sort((a, b) => (b.top1_share_pct ?? -1) - (a.top1_share_pct ?? -1));
  return (
    <div className={card}>
      <h2 className={h2}>Where the change came from</h2>
      <p className={sub}>The biggest single contributor along each dimension. Click a row to see it as a waterfall.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-[13px]">
          <thead className="text-[11px] uppercase tracking-wide text-slate-500">
            <tr><th className="py-2 pr-2">Dimension</th><th className="pr-2">Top contributor</th>
              <th className="pr-2 text-right">Impact</th><th className="pr-2 text-right">Share</th><th>Pattern</th></tr>
          </thead>
          <tbody>
            {sorted.map((d) => (
              <tr key={d.key} onClick={() => onSelect(d.key)}
                  className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${selected === d.key ? "bg-red-50/50" : ""}`}>
                <td className="py-2 pr-2 text-slate-500">{d.label}</td>
                <td className="pr-2 font-semibold text-slate-900">{d.top_segment ?? "–"}</td>
                <td className="pr-2 text-right tabular-nums">
                  {d.top_segment ? fmtDelta(fmt, d.rows.find((r) => r.segment === d.top_segment)?.contribution) : "–"}</td>
                <td className="pr-2 text-right font-semibold tabular-nums">{d.top1_share_pct != null ? `${d.top1_share_pct.toFixed(0)}%` : "–"}</td>
                <td><PatternTag p={d.pattern} />{d.offsets && <span className="ml-1 text-[10px] text-slate-500">others offset</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        “Concentrated” = one value explains most of the change, so that is where to look. “Spread out” = no single culprit.
        A share can pass 100% when other segments move the opposite way.
        {data.unavailable_dimensions.length > 0 && (
          <> Not available here: {data.unavailable_dimensions.map((u) => u.label.toLowerCase()).join(", ")} ({data.unavailable_dimensions[0].reason}).</>
        )}
      </p>
    </div>
  );
}

// ---- Detail table of one dimension ------------------------------------------
export function DimensionTable({
  data, dim, onDrill,
}: { data: RcaAnalysis; dim: RcaDimension; onDrill: (dim: string, seg: string) => void }) {
  const m = data.metric;
  return (
    <div className={card}>
      <h2 className={h2}>By {dim.label.toLowerCase()}</h2>
      <p className={sub}>{dim.segments} segments in this slice; the {dim.rows.length} biggest are listed, the rest are grouped.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-[13px]">
          <thead className="text-[11px] uppercase tracking-wide text-slate-500">
            <tr><th className="py-2 pr-2">{dim.label}</th><th className="pr-2 text-right">Impact</th><th className="pr-2 text-right">Share of change</th>
              <th className="pr-2 text-right">Now → {data.compare.label}</th><th className="pr-2 text-right">{m.weight_label || "Size"}</th>
              <th className="pr-2">Its own history</th><th /></tr>
          </thead>
          <tbody>
            {dim.rows.map((r) => (
              <tr key={r.segment} className="border-t border-slate-100">
                <td className="py-2 pr-2 font-semibold text-slate-900">
                  {r.segment}
                  {r.parts && <span className="block text-[11px] font-normal text-slate-500">
                    {Object.entries(r.parts).map(([k, v]) => `${k} ${fmtDelta(m.fmt, v)}`).join(" · ")}</span>}
                </td>
                <td className="pr-2 text-right font-semibold tabular-nums">{fmtDelta(m.fmt, r.contribution)}</td>
                <td className="pr-2 text-right tabular-nums">{r.share_pct != null ? `${r.share_pct.toFixed(0)}%` : "–"}</td>
                <td className="pr-2 text-right tabular-nums text-slate-600">{fmtValue(m.fmt, r.own_current)} → {fmtValue(m.fmt, r.own_base)}</td>
                <td className="pr-2 text-right tabular-nums text-slate-600">{r.weight_pct != null ? `${r.weight_pct.toFixed(0)}%` : "–"}</td>
                <td className="pr-2"><EvidenceChip ev={r.evidence} /></td>
                <td><button type="button" onClick={() => onDrill(dim.key, r.segment)}
                            className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-50">Drill in</button></td>
              </tr>
            ))}
            {dim.other && (
              <tr className="border-t border-slate-100 text-slate-500">
                <td className="py-2 pr-2">{dim.other.label}</td>
                <td className="pr-2 text-right tabular-nums">{fmtDelta(m.fmt, dim.other.contribution)}</td>
                <td className="pr-2 text-right tabular-nums">{dim.other.share_pct != null ? `${dim.other.share_pct.toFixed(0)}%` : "–"}</td>
                <td colSpan={4} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Impact = this segment’s part of the change ({m.unit_word === "pp" ? "percentage points" : m.unit_word === "days" ? "days" : "rupees"}).
        “Its own history” asks whether the segment’s own {m.fmt === "percent" ? "level" : "change"} this month is unusual against its other months.
      </p>
    </div>
  );
}
