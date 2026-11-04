"use client";

import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { inrCompact } from "@/lib/format";

// Expiry Risk Trend as a month-by-month "butterfly": one row per month, Near Expiry growing to the
// LEFT of the centre line and Expiry to the RIGHT. Presentation only - the numbers, colours and the
// click-a-month drill-down come from the same chart spec the old column chart used.
const NEAR = "Near Expiry";
const EXP = "Expiry";
const ROW_PX = 14;          // height per month; compact enough to sit beside a normal-sized card
const BAR_PX = 10;
const Y_AXIS_W = 56;

// Round tick step (1, 2 or 5 x 10^k) so the axis reads 0.05, 0.10, 0.15 ... instead of arbitrary cut-offs.
function niceStep(max: number): number {
  const raw = max / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / mag;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * mag;
}

export default function ExpiryTrendChart({ rows, nearColor, expColor, onPick, clickable }: {
  rows: { x: string; [k: string]: string | number }[];
  nearColor: string; expColor: string;
  onPick: (month: string) => void; clickable: boolean;
}) {
  // Near Expiry is plotted as a negative number so it extends to the left; labels show the real value.
  const data = rows.map((r) => ({ x: r.x, [NEAR]: -Math.abs(Number(r[NEAR] ?? 0)), [EXP]: Math.abs(Number(r[EXP] ?? 0)) }));
  const height = Math.max(180, data.length * ROW_PX + 62);
  // Axis: zero in the centre line, each side rounded up to a whole tick step.
  const maxNear = Math.max(0, ...data.map((d) => -d[NEAR]));
  const maxExp = Math.max(0, ...data.map((d) => d[EXP]));
  const step = maxNear + maxExp > 0 ? niceStep(Math.max(maxNear, maxExp)) : 1;
  const lo = -Math.ceil(maxNear / step) * step;
  const hi = Math.ceil(maxExp / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" barGap={-BAR_PX} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}
                  onClick={(e) => clickable && e?.activeLabel && onPick(String(e.activeLabel))}
                  style={{ cursor: clickable ? "pointer" : undefined }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          {/* Domain always contains zero so both sides are drawn from the centre line. */}
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => inrCompact(Math.abs(v))}
                 domain={[lo, hi]} ticks={ticks} allowDataOverflow />
          <YAxis type="category" dataKey="x" width={Y_AXIS_W} tick={{ fontSize: 10 }} interval={0} tickLine={false} />
          <Tooltip formatter={(v) => inrCompact(Math.abs(Number(v)))} cursor={{ fill: "rgba(59,69,89,0.06)" }}
                   contentStyle={{ color: "#0f172a" }} labelStyle={{ color: "#0f172a" }}
                   itemSorter={(item) => (item.name === NEAR ? 0 : 1)} />
          <Legend wrapperStyle={{ fontSize: 12, fontWeight: 400 }} itemSorter={(item) => (item.value === NEAR ? 0 : 1)} />
          <ReferenceLine x={0} stroke="#475569" />
          {/* barGap = -barSize puts both bars on the same line: one grows left of zero, the other right. */}
          <Bar dataKey={NEAR} fill={nearColor} barSize={BAR_PX} />
          <Bar dataKey={EXP} fill={expColor} barSize={BAR_PX} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
