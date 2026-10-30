"use client";

import { fmtDelta, fmtValue, toneOf, TONE_COLOR, TOTAL_COLOR } from "@/lib/rca-format";
import type { RcaAnalysis, RcaDimension } from "@/lib/rca-types";

interface Step { name: string; kind: "total" | "delta" | "other" | "effect"; value: number; segment?: string }

// Waterfall of one dimension: comparison value -> each contributor -> current value.
// Custom SVG (not Recharts): floating bars on a zoomed axis need exact control, and the
// axis is labelled whenever it does not start at zero. Clicking a contributor drills into it.
export default function RcaWaterfall({
  data, dim, onDrill,
}: { data: RcaAnalysis; dim: RcaDimension; onDrill: (dim: string, segment: string) => void }) {
  const fmt = data.metric.fmt;
  const { base, current } = data.headline;
  const steps: Step[] = [{ name: data.compare.label, kind: "total", value: base }];
  dim.rows.forEach((r) => steps.push({ name: r.segment, kind: "delta", value: r.contribution ?? 0, segment: r.segment }));
  if (dim.other?.contribution != null) steps.push({ name: dim.other.label, kind: "other", value: dim.other.contribution });
  data.effects.forEach((e) => steps.push({ name: e.label, kind: "effect", value: e.contribution ?? 0 }));
  steps.push({ name: data.period.label, kind: "total", value: current });

  // Running levels: where each floating bar starts and ends.
  let run = base;
  const bars = steps.map((s) => {
    if (s.kind === "total") return { ...s, lo: Math.min(0, s.value), hi: s.value, start: s.value, end: s.value };
    const start = run; run += s.value;
    return { ...s, lo: Math.min(start, run), hi: Math.max(start, run), start, end: run };
  });

  const levels = bars.flatMap((b) => [b.start, b.end]);
  const lvlMin = Math.min(...levels), lvlMax = Math.max(...levels);
  const span = Math.max(lvlMax - lvlMin, Math.abs(lvlMax) * 0.02, 1e-9);
  let yMin = lvlMin - span * 0.45, yMax = lvlMax + span * 0.3;
  if (lvlMin >= 0 && yMin < 0) yMin = 0;
  if (fmt === "percent") yMax = Math.min(yMax, 100);
  const zoomed = yMin > 0;

  const W = 820, H = 360, L = 64, R = 16, T = 30, B = 84;
  const y = (v: number) => T + ((yMax - v) / (yMax - yMin)) * (H - T - B);
  const bw = (W - L - R) / bars.length;
  const ticks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4);
  const tickFmt = (v: number) => (fmt === "percent" ? `${v.toFixed(1)}%` : fmt === "days" ? v.toFixed(1) : fmtValue(fmt, v));

  const wrap = (s: string) => {
    const words = s.split(" "), lines: string[] = []; let cur = "";
    words.forEach((w) => { if ((cur + " " + w).trim().length > 13 && cur) { lines.push(cur); cur = w; } else cur = (cur + " " + w).trim(); });
    lines.push(cur);
    return lines.slice(0, 3).map((l, i, a) => (i === 2 && a.length === 3 && s.length > 36 ? l.slice(0, 11) + "…" : l));
  };

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label={`Waterfall of ${data.metric.label} by ${dim.label}`}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="#e2e8f0" />
            <text x={L - 8} y={y(t) + 4} fontSize="11" fill="#64748b" textAnchor="end">{tickFmt(t)}</text>
          </g>
        ))}
        {data.compare.key === "target" && (
          <text x={W - R} y={T - 12} fontSize="11" fill="#475569" textAnchor="end">Bars start from the target</text>
        )}
        {bars.map((b, i) => {
          const x = L + i * bw + bw * 0.16, w = bw * 0.68;
          const isTotal = b.kind === "total";
          const color = isTotal ? TOTAL_COLOR : TONE_COLOR[toneOf(data.metric.higher_is, b.value)];
          const top = y(b.hi), h = Math.max(y(Math.max(b.lo, yMin)) - top, 2);   // never draw below the axis
          const clickable = b.kind === "delta" && b.segment;
          const label = isTotal ? fmtValue(fmt, b.value) : fmtDelta(fmt, b.value);
          const prev = bars[i - 1];
          return (
            <g key={i} style={clickable ? { cursor: "pointer" } : undefined}
               onClick={clickable ? () => onDrill(dim.key, b.segment!) : undefined}>
              <title>{`${b.name}: ${label}${clickable ? " (click to drill in)" : ""}`}</title>
              {prev && <line x1={L + (i - 1) * bw + bw * 0.84} x2={x} y1={y(b.kind === "total" ? b.value : b.start)}
                             y2={y(b.kind === "total" ? b.value : b.start)} stroke="#94a3b8" />}
              <rect x={x} y={top} width={w} height={h} rx={3} fill={color} opacity={b.kind === "other" ? 0.55 : 1} />
              <text x={x + w / 2} y={top - 7} fontSize="12" fontWeight="700" fill="#1f2937" textAnchor="middle">{label}</text>
              {wrap(b.name).map((l, k) => (
                <text key={k} x={x + w / 2} y={H - B + 18 + k * 14} fontSize="11" fill="#475569" textAnchor="middle"
                      textDecoration={clickable ? "underline" : undefined}>{l}</text>
              ))}
            </g>
          );
        })}
      </svg>
      <p className="mt-1 text-[11px] text-slate-500">
        {zoomed ? "The axis does not start at zero, so bar heights are not proportional to the totals. " : ""}
        Click a contributor to drill into it.
      </p>
    </div>
  );
}
