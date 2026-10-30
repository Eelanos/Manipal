import type { Kpi } from "@/lib/types";

// Same structure for every card so labels, numbers and captions line up:
// label (one line) / big number / one short caption. The number is always the
// same dark colour; only the thin top bar signals risk.
const BAR: Record<string, string> = {
  risk: "bg-red-600",
  neutral: "bg-slate-400",
  positive: "bg-emerald-600",
};

export default function PredictKpi({ kpi }: { kpi: Kpi }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className={`h-1 ${BAR[kpi.tone] ?? BAR.neutral}`} />
      <div className="flex flex-1 flex-col gap-1 px-5 py-4">
        <p className="truncate text-xs font-semibold uppercase tracking-wide text-slate-600">{kpi.label}</p>
        <p className="text-3xl font-semibold tabular-nums text-slate-900">{kpi.display}</p>
        <p className="text-sm text-slate-600">
          {kpi.delta_pct !== null && (
            <span className="mr-1 font-medium text-slate-800">
              {kpi.delta_pct >= 0 ? "▲" : "▼"} {Math.abs(kpi.delta_pct).toFixed(1)}%
            </span>
          )}
          {kpi.note}
        </p>
      </div>
    </div>
  );
}
