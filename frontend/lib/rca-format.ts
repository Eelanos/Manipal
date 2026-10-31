import { inrCompact } from "./format";
import type { EntityFlag, RcaFmt, RowTone } from "./rca-types";

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

// ---- status badges ----------------------------------------------------------------------------
/** The wording and colours of a status badge. The rule behind it is stated on screen from the backend thresholds. */
export function flagMeta(flag: EntityFlag | undefined, tone: RowTone | undefined) {
  const t = tone ?? "neutral";
  const palette = t === "bad"
    ? { chip: "bg-red-50 text-red-800 ring-red-200", bar: "border-l-red-700", dot: "bg-red-600" }
    : t === "good"
      ? { chip: "bg-emerald-50 text-emerald-800 ring-emerald-200", bar: "border-l-emerald-600", dot: "bg-emerald-600" }
      : { chip: "bg-blue-50 text-blue-800 ring-blue-200", bar: "border-l-accent", dot: "bg-accent" };
  const quiet = { chip: "bg-slate-100 text-slate-600 ring-slate-200", bar: "border-l-slate-300", dot: "bg-slate-400" };
  switch (flag) {
    case "deviating":
      return { ...palette, text: t === "good" ? "HIGH · BETTER" : "HIGH", rank: 0,
               hint: "Moved a material part of the total AND unusually, against its own history." };
    case "watch":
      return { ...palette, chip: t === "bad" ? "bg-amber-50 text-amber-800 ring-amber-200" : palette.chip,
               text: t === "good" ? "MEDIUM · BETTER" : "MEDIUM", rank: 1,
               hint: "Moved a material part of the total, somewhat out of the ordinary for it." };
    case "normal":
      return { ...quiet, text: "NORMAL", rank: 2, hint: "Moved a material part of the total, but within its own normal range." };
    case "no_history":
      return { ...quiet, text: "NO HISTORY", rank: 3, hint: "Not enough months of history to judge." };
    default:
      return { ...quiet, text: "MINOR", rank: 4, hint: "Too small a part of the total movement to matter." };
  }
}
