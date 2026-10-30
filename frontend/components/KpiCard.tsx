import type { Kpi } from "@/lib/types";

// Red is reserved for risk flags only - never decorative. That rule holds
// across all dashboards.
const TONE: Record<string, string> = {
  neutral: "text-slate-900",
  positive: "text-emerald-700",
  risk: "text-red-600",
};

export default function KpiCard({ kpi }: { kpi: Kpi }) {
  return (
    <div className="kpi-card flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {kpi.label}
      </p>
      <p className={`mt-2 text-2xl font-semibold ${TONE[kpi.tone]}`}>
        {kpi.display}
      </p>
      {kpi.delta_pct !== null && (
        <p className={`mt-1 text-xs ${kpi.delta_pct >= 0 ? "text-emerald-600" : "text-red-600"}`}>
          {kpi.delta_pct >= 0 ? "up" : "down"} {Math.abs(kpi.delta_pct).toFixed(1)}%
        </p>
      )}
      {/* The calculation, in small print. Every metric where we had to pick a
          definition carries one - so the client corrects us in a sentence
          instead of quietly deciding the dashboard is wrong. */}
      {kpi.note && (
        <p className="mt-auto pt-2 text-[11px] leading-snug text-slate-400">
          {kpi.note}
        </p>
      )}
    </div>
  );
}
