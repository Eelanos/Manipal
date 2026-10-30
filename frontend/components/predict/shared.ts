// Presentation helpers for the Predictive Analysis page. No business rules here:
// every number and status comes from the API.

import { numberFull } from "@/lib/format";
import type { LineRow, PredictOptions } from "@/lib/predict-types";

// Status colours. Red is reserved for risk (Critical), matching every other page.
export const STATUS_COLOR: Record<string, string> = {
  Critical: "#c0392b",
  "Order soon": "#e08a1e",
  Healthy: "#2a9d8f",
  Excess: "#2f54d4",
  "No recent usage": "#94a3b8",
  "No stock record": "#cbd5e1",
};
export const statusColor = (s: string) => STATUS_COLOR[s] ?? "#94a3b8";

// Recharts tooltips inherit the page text colour, which is near-white in dark mode and unreadable on a
// white tooltip. Every tooltip in this page spreads these so the text colour is always explicit.
export const TOOLTIP = {
  contentStyle: { background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 6, fontSize: 12, color: "#0f172a" },
  labelStyle: { color: "#0f172a", fontWeight: 600 },
  itemStyle: { color: "#334155" },
};

export const card = "rounded-lg border border-slate-200 bg-white p-4 shadow-sm";
export const h2 = "text-sm font-semibold text-slate-900";
export const sub = "mt-0.5 text-xs text-slate-500";

export const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : numberFull(v));

export const dec1 = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 1 });

export function coverText(v: number | null, capped: boolean, opts: PredictOptions | null): string {
  if (v === null) return "—";
  if (capped) return `${opts?.horizon_days ?? ""}+`;
  return dec1(v);
}

export function orderInText(v: number | null): string {
  if (v === null) return "—";
  return v <= 0 ? "Now" : `In ${dec1(v)} d`;
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-12-31" -> "31 Dec 2026" without timezone surprises. */
export function dateText(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MON[m - 1]} ${y}`;
}
export function dayLabel(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${d} ${MON[m - 1]}`;
}

/** Crore formatting for chart axes/tooltips - the same convention as every other page. */
export const crore = (v: number) => `₹${(v / 1e7).toFixed(2)} Cr`;
export const croreShort = (v: number) => `${(v / 1e7).toFixed(1)}`;

/** Called when a row/bar is clicked: opens the item drill-down. */
export type OnPickItem = (r: Pick<LineRow, "item_id" | "unit_id">) => void;
