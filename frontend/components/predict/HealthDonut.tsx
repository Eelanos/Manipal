"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { HealthSlice } from "@/lib/predict-types";
import { TOOLTIP, card, crore, h2, num, statusColor, sub } from "./shared";

export default function HealthDonut({ slices, onPick }: { slices: HealthSlice[]; onPick: (status: string) => void }) {
  const total = slices.reduce((s, x) => s + x.lines, 0);
  const drawn = slices.filter((s) => s.lines > 0);
  return (
    <div className={`chart-card ${card}`}>
      <h2 className={h2}>Stock health</h2>
      <p className={sub}>Each item × unit line gets one status. Click a slice or row to see its lines. Value excludes expired stock.</p>
      {total === 0 ? (
        <p className="py-16 text-center text-sm text-slate-500">No stock lines in this selection.</p>
      ) : (
        <>
        <div className="mt-2 flex flex-col items-center gap-4 sm:flex-row">
          <div className="relative h-52 w-52 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={drawn} dataKey="lines" nameKey="status" innerRadius={58} outerRadius={92} paddingAngle={2}
                     stroke="none" cursor="pointer" onClick={(d) => onPick(String((d as { status?: string }).status))}>
                  {drawn.map((s) => <Cell key={s.status} fill={statusColor(s.status)} />)}
                </Pie>
                <Tooltip {...TOOLTIP} formatter={(v, n) => [`${num(Number(v))} lines`, String(n)]} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-2xl font-semibold text-slate-900">{num(total)}</span>
              <span className="text-[11px] text-slate-500">lines</span>
            </div>
          </div>
          <ul className="w-full flex-1 space-y-1">
            <li className="flex items-center gap-2 px-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <span className="h-3 w-3 shrink-0" /><span className="flex-1">Status</span>
              <span>Lines</span><span className="w-24 text-right">Stock value</span>
            </li>
            {slices.filter((s) => s.lines > 0).map((s) => (
              <li key={s.status}>
                <button type="button" onClick={() => onPick(s.status)} aria-label={`Show ${s.status} lines`}
                        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-100">
                  <i className="h-3 w-3 shrink-0 rounded-sm" style={{ background: statusColor(s.status) }} />
                  <span className="flex-1 text-slate-800">{s.status}</span>
                  <span className="tabular-nums text-slate-700">{num(s.lines)}</span>
                  <span className="w-24 text-right tabular-nums text-xs text-slate-500">{crore(s.stock_value)}</span>
                  <span aria-hidden className="text-slate-400">›</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        {/* The rule behind each status, with this run's numbers - so the donut explains itself. */}
        <div className="mt-4 border-t border-slate-100 pt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">How a line gets its status</p>
          <ul className="mt-2 space-y-1.5">
            {slices.filter((s) => s.lines > 0).map((s) => (
              <li key={s.status} className="flex gap-2 text-xs leading-snug text-slate-600">
                <i className="mt-1 h-2 w-2 shrink-0 rounded-sm" style={{ background: statusColor(s.status) }} />
                <span><b className="font-medium text-slate-800">{s.status}:</b> {s.rule}</span>
              </li>
            ))}
          </ul>
        </div>
        </>
      )}
    </div>
  );
}
