"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart,
  Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { inrCompact } from "@/lib/format";
import type { Chart as ChartSpec } from "@/lib/types";
import { useState } from "react";
import DrilldownModal from "./DrilldownModal";
import DrilldownDonut from "./DrilldownDonut";
import DrilldownUnitModal from "./DrilldownUnitModal";

// Qber palette: dark teal, red, blue, cyan, orange, purple, green, light cyan.
// Single-series bars take the first colour; the reference line stays red.
const COLORS = ["#3d6479", "#c0392b", "#2f54d4", "#5bbcd6",
                "#e08a1e", "#7b4fd1", "#2a9d8f", "#8fe3f5"];

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];  

const LEGEND_STYLE = { fontSize: 12, fontWeight: 400 };

function mergeSeries(spec: ChartSpec) {
  const byX = new Map<string, Record<string, string | number>>();
  spec.series.forEach((s) => {
    s.data.forEach((point) => {
      const rawX = point[spec.x_key];
      const label = spec.x_key === "month" && typeof rawX === "number"
        ? MONTHS[rawX] : String(rawX);
      const row = byX.get(label) ?? { x: label };
      row[s.name] = point.value ?? point.y ?? 0;
      byX.set(label, row);
    });
  });
  return Array.from(byX.values());
}

function makeFormatter(format: ChartSpec["value_format"]) {
  return (v: number) => {
    if (format === "percent") return `${v.toFixed(1)}%`;
    if (format === "number") return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    return inrCompact(v);
  };
}

export default function ChartPanel({ spec }: { spec: ChartSpec }) {
  const names = spec.series.map((s) => s.name);
  const data = mergeSeries(spec);
  const horizontal = spec.type === "hbar";
  // Recharts' default [0, auto] domain mis-draws all-negative bars (they hang from a non-zero edge and
  // look shorter than they are). Only when a series has negatives, anchor the axis so zero is always inside it.
  const hasNegative = data.some((row) => names.some((n) => Number(row[n]) < 0));
  const valueDomain: [(m: number) => number, (m: number) => number] | undefined = hasNegative
    ? [(m) => Math.min(0, m), (m) => Math.max(0, m)] : undefined;
  const fmt = makeFormatter(spec.value_format);
  const [drillMonth, setDrillMonth] = useState<string | null>(null);

  return (
    <div className="chart-card rounded-lg border border-slate-200 bg-white p-4">
      {/* Heading matches the legend below: same size, same weight, non-bold. */}
      <h3 className="mb-4 text-xs font-normal text-slate-700">{spec.title}</h3>
      <ResponsiveContainer width="100%" height={horizontal ? 360 : 280}>
        {spec.type === "combo" ? (
          // First series renders as bars, the rest as lines - one convention,
          // used consistently (actual as bars, BUD as the line).
          <ComposedChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="x" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} width={80} />
            <Tooltip formatter={(v) => fmt(Number(v))} 
              contentStyle={{ color: "#0f172a" }}
              labelStyle={{ color: "#0f172a" }}/>
            <Legend wrapperStyle={LEGEND_STYLE} />
            <Bar dataKey={names[0]} fill={COLORS[0]} radius={[4, 4, 0, 0]}
     cursor={spec.drilldown ? "pointer" : undefined}
     onClick={(d) => spec.drilldown && setDrillMonth(String(d.payload.x))} />
            {names.slice(1).map((n, i) => (
              <Line key={n} type="monotone" dataKey={n}
                    stroke={COLORS[(i + 1) % COLORS.length]}
                    strokeWidth={2} dot={false} />
            ))}
          </ComposedChart>
        ) : spec.type === "line" ? (
          <LineChart data={data}
                      onClick={(e) => spec.drilldown && e?.activeLabel && setDrillMonth(String(e.activeLabel))}
                      style={{ cursor: spec.drilldown ? "pointer" : undefined }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="x" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} width={80} />
            <Tooltip formatter={(v) => fmt(Number(v))}
                     contentStyle={{ color: "#0f172a" }}
                     labelStyle={{ color: "#0f172a" }} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            {spec.reference_line !== null && (
              <ReferenceLine y={spec.reference_line} stroke="#dc2626"
                             strokeDasharray="4 4" />
            )}
            {names.map((n, i) => (
              <Line key={n} type="monotone" dataKey={n}
                    stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
                ) : spec.type === "donut" ? (
          <PieChart>
            <Tooltip formatter={(v) => fmt(Number(v))}
                     contentStyle={{ color: "#0f172a" }}
                     labelStyle={{ color: "#0f172a" }} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            <Pie data={data} dataKey={names[0]} nameKey="x"
                 innerRadius={60} outerRadius={100}
                 cursor={spec.drilldown ? "pointer" : undefined}
                 onClick={(d) => spec.drilldown && setDrillMonth(String(d.payload?.x ?? d.name))}>
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        ) : (
          <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"}
                    onClick={(e) => spec.drilldown && e?.activeLabel && setDrillMonth(String(e.activeLabel))}
                    style={{ cursor: spec.drilldown ? "pointer" : undefined }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            {horizontal ? (
              <>
                <XAxis type="number" tickFormatter={fmt} tick={{ fontSize: 11 }} domain={valueDomain} />
                <YAxis type="category" dataKey="x" width={160}
                       tick={{ fontSize: 11 }} />
              </>
            ) : (
              <>
                <XAxis dataKey="x" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} width={80} domain={valueDomain} />
              </>
            )}
            <Tooltip formatter={(v) => fmt(Number(v))}
                     contentStyle={{ color: "#0f172a" }}
                     labelStyle={{ color: "#0f172a" }} />
            {names.length > 1 && <Legend wrapperStyle={LEGEND_STYLE} />}
            {names.map((n, i) => (
              <Bar key={n} dataKey={n} fill={COLORS[i % COLORS.length]}
                   stackId={spec.type === "stacked_bar" ? "a" : undefined} />
            ))}
          </BarChart>
        )}
            </ResponsiveContainer>
      {spec.drilldown && drillMonth && (
        spec.id === "non_moving_trend" || spec.id === "expiry_risk" || spec.id === "formulary_by_package" ? (
          <DrilldownDonut
            title={
              spec.id === "expiry_risk" ? `Expiry Risk by Department — ${drillMonth}`
              : spec.id === "non_moving_trend" ? `Non Moving Stock by Department — ${drillMonth}`
              : `Package/Formulary Mix — ${drillMonth}`
            }
            data={(spec.drilldown[drillMonth] ?? []) as { name: string; value: number }[]}
            onClose={() => setDrillMonth(null)}
          />
        ) : spec.id === "consumption_trend" ? (
          <DrilldownUnitModal
            title={`Unit-wise Stock & Inventory Days — ${drillMonth}`}
            rows={(spec.drilldown[drillMonth] ?? []) as { Unit: string; Stock: number; "Inventory Days": number }[]}
            onClose={() => setDrillMonth(null)}
          />
        ) : (
          <DrilldownModal
            title={(() => {
              const labels: Record<string, string> = {
                inventory_days_trend: "Department-wise Stock Value",
                value_vs_consumption: "Department-wise Consumption",
                consumption_trend: "Department-wise Consumption",
                closing_stock_ageing: "Department-wise Closing Stock Value",
                top_locations_consumption: "Top Items (Consumption)",
                top_locations_inventory: "Top Items (Stock Value)",
                compliance_trend: "Off-Formulary Items",
                ip_op_compliance: "Department-wise Compliance Value",
                mix_scheme: "Molecule/Brand Breakdown",
                mix_cash_tpa: "Molecule/Brand Breakdown",
                by_doctor: "Molecule Breakdown",
                by_molecule: "Doctor/Brand Breakdown",
                by_item: "Doctor Breakdown",
                tier_mix: "Top Molecule/Brand",
                package_split: "Top Items",
              };
              return `${labels[spec.id] ?? "Department-wise Value"} — ${drillMonth}`;
            })()}
            rows={(spec.drilldown[drillMonth] ?? []) as { Department: string; Value: number }[]}
            onClose={() => setDrillMonth(null)}
          />
        )
      )}
    </div>
  );
}