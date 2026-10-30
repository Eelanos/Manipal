"use client";

import type { RcaEvidence, RcaFmt } from "@/lib/rca-types";
import { fmtDelta, fmtValue } from "@/lib/rca-format";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const lab = (ym: string) => `${MON[Number(ym.slice(5, 7)) - 1]} ${ym.slice(2, 4)}`;

// The metric's history with its normal range (average +/- 1 standard deviation) shaded,
// and the selected month marked. Answers "is this a real change or normal wobble?".
export default function RcaEvidenceChart({ ev, fmt }: { ev: RcaEvidence; fmt: RcaFmt }) {
  if (!ev.available || !ev.history || ev.mean == null || ev.sd == null) {
    return <p className="text-sm text-slate-500">{ev.reason ?? "No history available."}</p>;
  }
  const pts = ev.history.filter((h) => h.value !== null) as { month: string; value: number }[];
  const W = 640, H = 230, L = 58, R = 16, T = 18, B = 32;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals, ev.mean - ev.sd), hi = Math.max(...vals, ev.mean + ev.sd);
  const pad = (hi - lo) * 0.12 || 1;
  const yMin = lo - pad, yMax = hi + pad;
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(pts.length - 1, 1);
  const y = (v: number) => T + ((yMax - v) / (yMax - yMin)) * (H - T - B);
  const isLevel = ev.basis === "level";
  const tf = (v: number) => (isLevel ? fmtValue(fmt, v) : fmtDelta(fmt, v));
  const fi = pts.findIndex((p) => p.month === ev.focus_month);
  const line = pts.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const ticks = [yMin + pad * 0.3, (yMin + yMax) / 2, yMax - pad * 0.3];
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="History with normal range">
        {ticks.map((t, i) => (
          <g key={i}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="#e2e8f0" />
            <text x={L - 8} y={y(t) + 4} fontSize="10.5" fill="#64748b" textAnchor="end">{tf(t)}</text></g>
        ))}
        <rect x={L} y={y(ev.mean + ev.sd)} width={W - L - R} height={y(ev.mean - ev.sd) - y(ev.mean + ev.sd)} fill="#3b4559" opacity={0.1} />
        <line x1={L} x2={W - R} y1={y(ev.mean)} y2={y(ev.mean)} stroke="#64748b" strokeDasharray="4 3" />
        <polyline points={line} fill="none" stroke="#3b4559" strokeWidth={2} strokeLinejoin="round" />
        {[0, Math.floor(pts.length / 4), Math.floor(pts.length / 2), Math.floor((3 * pts.length) / 4), pts.length - 1].map((i) => (
          <text key={i} x={x(i)} y={H - 10} fontSize="10.5" fill="#64748b" textAnchor="middle">{lab(pts[i].month)}</text>
        ))}
        {fi >= 0 && (
          <g>
            <circle cx={x(fi)} cy={y(pts[fi].value)} r={6.5} fill="#a4262c" stroke="#fff" strokeWidth={2} />
            <text x={x(fi) + (fi > pts.length / 2 ? -11 : 11)} y={y(pts[fi].value) - 9} fontSize="12" fontWeight="700" fill="#1f2937" stroke="#ffffff" strokeWidth={4} paintOrder="stroke"
                  textAnchor={fi > pts.length / 2 ? "end" : "start"}>{lab(pts[fi].month)}: {tf(pts[fi].value)}</text>
          </g>
        )}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500">
        <span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm bg-nav/20 align-[-1px]" />
          Normal range (average ± 1 standard deviation): {tf(ev.mean - ev.sd)} to {tf(ev.mean + ev.sd)}</span>
        <span><i className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full bg-brand align-[-1px]" />Selected month</span>
      </div>
    </div>
  );
}
