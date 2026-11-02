"use client";

import {
  Bar, CartesianGrid, ComposedChart, ErrorBar, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Forecast, ForecastPoint } from "@/lib/predict-types";
import { card, crore, croreShort, h2, sub } from "./shared";

const ACTUAL = "#3d6479";
const FORECAST = "#5bbcd6";

interface Row extends ForecastPoint {
  err: [number, number] | null;   // distance from the forecast to the low / high end of the range
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow">
      <p className="font-semibold text-slate-900">{p.label}</p>
      {p.actual !== null && <p className="text-slate-700">Actual: {crore(p.actual)}</p>}
      {p.forecast !== null && (
        <>
          <p className="text-slate-700">Forecast: {crore(p.forecast)}</p>
          {p.low !== null && p.high !== null && (
            <p className="text-slate-500">Likely range: {crore(p.low)} – {crore(p.high)}</p>
          )}
        </>
      )}
    </div>
  );
}

export default function ForecastChart({ f }: { f: Forecast }) {
  const data: Row[] = f.points.map((p) => ({
    ...p,
    err: p.forecast !== null && p.low !== null && p.high !== null
      ? [p.forecast - p.low, p.high - p.forecast] : null,
  }));

  return (
    <div className={`chart-card ${card}`}>
      <h2 className={h2}>Expected demand, next 3 months</h2>
      <p className={sub}>
        Dark = actual, blue = forecast (recent daily usage × the month&apos;s usual pattern).
        {f.range_available ? " Whisker = likely range." : ""}
        {f.accuracy_pct !== null && (
          <span className="block">About {f.accuracy_pct.toFixed(0)}% accurate when tested on past months.</span>
        )}
      </p>
      {!f.has_forecast ? (
        <p className="py-16 text-center text-sm text-slate-500">
          Not enough usage history in this selection to forecast.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} angle={-30} textAnchor="end" height={52} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={croreShort} width={44}
                   label={{ value: "₹ Cr", angle: -90, position: "insideLeft", fontSize: 11, fill: "#64748b" }} />
            <Tooltip content={<Tip />} cursor={{ fill: "rgba(59,69,89,0.06)" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="actual" name="Actual" fill={ACTUAL} radius={[3, 3, 0, 0]} />
            <Bar dataKey="forecast" name="Forecast" fill={FORECAST} radius={[3, 3, 0, 0]}>
              {f.range_available && <ErrorBar dataKey="err" width={6} stroke="#1f2937" strokeWidth={1.5} />}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {f.has_forecast && <ForecastTable f={f} />}
    </div>
  );
}

// The three forecast months as numbers, next to the same month a year earlier (the matching actual bar).
function ForecastTable({ f }: { f: Forecast }) {
  const rows = f.points.filter((p) => p.forecast !== null).map((p) => {
    const [y, m] = p.month.split("-");
    const ly = f.points.find((x) => x.month === `${Number(y) - 1}-${m}` && x.actual !== null)?.actual ?? null;
    const chg = ly && ly > 0 && p.forecast !== null ? (p.forecast / ly - 1) * 100 : null;
    return { p, ly, chg };
  });
  return (
    <table className="mt-3 w-full border-t border-slate-100 text-sm">
      <thead>
        <tr className="text-[11px] uppercase tracking-wide text-slate-500">
          <th className="py-2 text-left font-semibold">Month</th>
          <th className="py-2 text-right font-semibold">Forecast</th>
          <th className="py-2 text-right font-semibold" title="Actual spend in the same month a year earlier">Same month, last year</th>
          <th className="py-2 text-right font-semibold">Change</th>
        </tr>
      </thead>
      <tbody className="text-slate-700">
        {rows.map(({ p, ly, chg }) => (
          <tr key={p.month} className="border-t border-slate-100">
            <td className="py-1.5 text-slate-900">{p.label}</td>
            <td className="py-1.5 text-right font-semibold tabular-nums text-slate-900">{crore(p.forecast as number)}</td>
            <td className="py-1.5 text-right tabular-nums">{ly !== null ? crore(ly) : "—"}</td>
            <td className="py-1.5 text-right tabular-nums">{chg !== null ? `${chg >= 0 ? "▲" : "▼"} ${Math.abs(chg).toFixed(1)}%` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
