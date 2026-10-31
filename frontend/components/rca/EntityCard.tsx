"use client";

import { fmtDelta, fmtValue, flagMeta } from "@/lib/rca-format";
import type { LensEntity, RcaLens, TopCause } from "@/lib/rca-types";
import { StatusBadge } from "./RcaShell";

/** "46% of the change", or a plain statement when the entity moved against the overall change. */
export function shareText(share: number | null | undefined, flat: boolean): string {
  if (flat) return "total is flat";
  if (share == null) return "";
  if (share < 0) return "moved against the overall change";
  return `${share.toFixed(0)}% of the total change`;
}

function toneText(tone: string) {
  return tone === "bad" ? "text-red-700" : tone === "good" ? "text-emerald-700" : "text-slate-900";
}

// undefined = still loading, null = nothing stands out
export function CauseChip({ cause }: { cause: TopCause | null | undefined }) {
  if (cause === undefined) return <div className="h-[42px] animate-pulse rounded bg-slate-100" />;
  if (cause === null) return <div className="rounded bg-slate-50 px-2.5 py-1.5 text-[12px] text-slate-500">No single driver stands out</div>;
  return (
    <div className="rounded bg-slate-50 px-2.5 py-1.5" title={`${cause.share_of_slice_pct.toFixed(0)}% of this change sits in ${cause.segment}${
      cause.weight_in_slice_pct != null ? `, which is only ${cause.weight_in_slice_pct.toFixed(0)}% of the base` : ""}`}>
      <p className="truncate text-[12.5px] font-semibold text-slate-900">{cause.segment}</p>
      <p className="truncate text-[11px] text-slate-500">{cause.dim_label} · {cause.share_of_slice_pct.toFixed(0)}% of the change
        {cause.weight_in_slice_pct != null ? ` vs ${cause.weight_in_slice_pct.toFixed(0)}% of base` : ""}</p>
    </div>
  );
}

export default function EntityCard({
  e, lens, cause, onOpen,
}: { e: LensEntity; lens: RcaLens; cause: TopCause | null | undefined; onOpen: () => void }) {
  const fmt = lens.metric.fmt;
  const meta = flagMeta(e.flag, e.tone);
  return (
    <button type="button" onClick={onOpen}
            className={`flex h-full flex-col rounded-lg border border-l-4 border-slate-200 bg-white px-3 py-2.5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${meta.bar}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 truncate text-[14.5px] font-semibold text-slate-900" title={e.segment}>{e.segment}</h3>
        <StatusBadge flag={e.flag} tone={e.tone} />
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <p className={`shrink-0 whitespace-nowrap text-[20px] font-extrabold leading-tight tracking-tight ${toneText(e.tone)}`}>{fmtDelta(fmt, e.contribution)}</p>
        <p className="min-w-0 truncate text-[11px] text-slate-500" title={shareText(e.share_pct, lens.headline.flat)}>{shareText(e.share_pct, lens.headline.flat)}</p>
      </div>
      <p className="text-[11.5px] text-slate-600">
        {fmtValue(fmt, e.own_current)} <span className="text-slate-400">vs</span> {fmtValue(fmt, e.own_base)}
        <span className="text-slate-400"> · its own {lens.compare.label}</span>
      </p>
      <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Top driver inside</p>
      <div className="mt-0.5"><CauseChip cause={cause} /></div>
    </button>
  );
}
