"use client";

import { fmtDelta, toneOf, TONE_COLOR } from "@/lib/rca-format";
import type { RcaDimension, RcaFmt } from "@/lib/rca-types";

// One bar. A top-level component (not defined inside ImpactBars) so React does not rebuild it on every render.
function Row({ label, v, onClick, faint, big, fmt, higherIs }: {
  label: string; v: number; onClick?: () => void; faint?: boolean; big: number; fmt: RcaFmt; higherIs: string;
}) {
  const w = (Math.abs(v) / big) * 32;                  // percent of the track, each side of the centre line
  const color = TONE_COLOR[toneOf(higherIs, v)];
  return (
    <div className={`grid grid-cols-[9.5rem_1fr] items-center gap-2 py-0.5 ${onClick ? "cursor-pointer rounded hover:bg-slate-50" : ""}`}
         onClick={onClick} title={`${label}: ${fmtDelta(fmt, v)}`}>
      <span className={`truncate text-right text-[12px] ${faint ? "text-slate-400" : "text-slate-600"}`}>{label}</span>
      <div className="relative h-[18px]">
        <div className="absolute inset-y-0 left-1/2 w-px bg-slate-300" />
        <div className="absolute inset-y-0.5 rounded-sm" style={{
          background: color, opacity: faint ? 0.5 : 1, width: `${Math.max(w, 0.8)}%`,
          ...(v < 0 ? { right: "50%" } : { left: "50%" }),
        }} />
        <span className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap text-[11px] font-semibold text-slate-800"
              style={v < 0 ? { right: `calc(50% + ${Math.max(w, 0.8)}% + 4px)` } : { left: `calc(50% + ${Math.max(w, 0.8)}% + 4px)` }}>
          {fmtDelta(fmt, v)}
        </span>
      </div>
    </div>
  );
}

// Diverging bars: each segment's part of the change, left of the line = pulled the number down,
// right = pushed it up. Colour says whether that is good or bad for the KPI. The bars are plain
// sizes (not cumulative), so they are easy to read at a glance; the total is stated underneath.
export default function ImpactBars({
  dim, fmt, higherIs, total, onPick, max = 8,
}: { dim: RcaDimension; fmt: RcaFmt; higherIs: string; total: number | null; onPick?: (segment: string) => void; max?: number }) {
  const rows = [...dim.rows].sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0)).slice(0, max);
  const rest = dim.rows.length - rows.length + (dim.other?.count ?? 0);
  const restSum = dim.rows.filter((r) => !rows.includes(r)).reduce((s, r) => s + (r.contribution ?? 0), 0) + (dim.other?.contribution ?? 0);
  const big = Math.max(...rows.map((r) => Math.abs(r.contribution ?? 0)), Math.abs(restSum), 1e-12);
  const shared = { big, fmt, higherIs };
  return (
    <div>
      {rows.map((r) => <Row key={r.segment} label={r.segment} v={r.contribution ?? 0} onClick={onPick ? () => onPick(r.segment) : undefined} {...shared} />)}
      {rest > 0 && <Row label={`All other (${rest})`} v={restSum} faint {...shared} />}
      <p className="mt-2 border-t border-slate-100 pt-2 text-[11.5px] text-slate-500">
        All {dim.segments} {dim.label.toLowerCase()} values together: <b className="text-slate-800">{fmtDelta(fmt, total)}</b>
      </p>
    </div>
  );
}
