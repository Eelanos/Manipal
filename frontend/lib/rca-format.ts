import { inrCompact } from "./format";
import type { RcaFmt } from "./rca-types";

// One place that turns an RCA number into text. "pp" = percentage points.
const MINUS = "−";

export function fmtValue(fmt: RcaFmt, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  if (fmt === "percent") return `${v.toFixed(1)}%`;
  if (fmt === "days") return `${v.toFixed(1)} days`;
  return inrCompact(v);
}

/** A change, with its sign: +3.57 pp, −₹0.42 Cr, +1.2 days. */
export function fmtDelta(fmt: RcaFmt, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  const sign = v > 0 ? "+" : v < 0 ? MINUS : "";
  const a = Math.abs(v);
  if (fmt === "percent") return `${sign}${a.toFixed(2)} pp`;
  if (fmt === "days") return `${sign}${a.toFixed(a < 1 ? 2 : 1)} days`;
  return `${sign}${inrCompact(a)}`;
}

/** Colour for a change: red = moves the KPI the wrong way, teal = the right way. */
export type Tone = "bad" | "good" | "up" | "down";
export function toneOf(higherIs: string, v: number): Tone {
  if (higherIs === "better") return v < 0 ? "bad" : "good";
  if (higherIs === "worse") return v > 0 ? "bad" : "good";
  return v >= 0 ? "up" : "down";
}
export const TONE_COLOR: Record<Tone, string> = {
  bad: "#a4262c", good: "#2a9d8f", up: "#2f54d4", down: "#e08a1e",
};
export const TOTAL_COLOR = "#3b4559";
