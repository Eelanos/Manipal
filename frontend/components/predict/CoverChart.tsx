"use client";

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CoverRow, PredictOptions } from "@/lib/predict-types";
import { TOOLTIP, card, coverText, h2, statusColor, sub } from "./shared";

const short = (s: string) => (s.length > 30 ? `${s.slice(0, 29)}…` : s);

export default function CoverChart({ rows, leadDays, options }: {
  rows: CoverRow[]; leadDays: number; options: PredictOptions | null;
}) {
  return (
    <div className={`chart-card flex flex-col ${card}`}>
      <h2 className={h2}>Lowest days of cover</h2>
      <p className={sub}>
        Days the current stock lasts. Bars left of the dashed line run out before a new order ({leadDays}d) could arrive.
      </p>
      {rows.length === 0 ? (
        <p className="py-16 text-center text-sm text-slate-500">No items with recent usage in this selection.</p>
      ) : (
        // The card can be stretched by its neighbour in the grid: let the chart use that height
        // (never less than its natural size) instead of leaving blank space under the bars.
        <div className="min-h-0 flex-1" style={{ minHeight: Math.max(220, rows.length * 30 + 60) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 22, right: 150, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
            {/* Always wide enough to show the delivery-time line, even when every bar is short. */}
            <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} domain={[0, (max: number) => Math.max(max, leadDays * 2)]}
                   label={{ value: "days", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "#64748b" }} />
            <YAxis type="category" dataKey="label" width={190} tick={{ fontSize: 11 }} tickFormatter={short} interval={0} />
            <Tooltip {...TOOLTIP} formatter={(v, _n, item) => [coverText(Number(v), (item?.payload as CoverRow).capped, options) + " days", "Cover"]}
                     labelFormatter={(l) => String(l)} />
            <ReferenceLine x={leadDays} stroke="#c0392b" strokeDasharray="5 4"
                           label={{ value: "Delivery time", position: "top", fontSize: 10, fill: "#c0392b" }} />
            {/* minPointSize: a stock-out (0 days) still draws a visible stub and its label. */}
            <Bar dataKey="cover_days" radius={[0, 3, 3, 0]} minPointSize={5}>
              {rows.map((r) => <Cell key={`${r.unit_id}${r.item_id}`} fill={statusColor(r.status)} />)}
              {/* Custom label: a zero-length bar (out of stock) still gets its text. */}
              <LabelList dataKey="cover_days" content={(p) => {
                const v = Number(p.value);
                const row = rows[Number(p.index)];
                const days = `${coverText(v, v >= (options?.horizon_days ?? Infinity), options)} d`;
                const text = row?.on_order > 0 ? `${days} · order on the way` : days;
                return (
                  <text x={Number(p.x) + Number(p.width) + 6} y={Number(p.y) + Number(p.height) / 2 + 4}
                        fontSize={11} fill="#64748b">{text}</text>
                );
              }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
