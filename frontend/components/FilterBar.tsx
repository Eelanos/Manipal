"use client";

import { usePathname } from "next/navigation";
import type { FilterOptions, FilterState } from "@/lib/types";

const PRESET_LABELS: Record<string, string> = {
  this_month: "This Month",
  this_quarter: "This Quarter",
  ytd: "FY YTD",
  fy2025: "FY2025",
  fy2026: "FY2026",
  full_range: "Full Range",
};

interface Props {
  options: FilterOptions | null;
  value: FilterState;
  onChange: (next: FilterState) => void;
}

// One row above every page: Unit, Period, Product Group, Department. The
// network hierarchy (Region/Zone/Cluster) is scoped to two units for this
// presentation, so only Unit is shown; see app/config.py: ACTIVE_UNITS to
// restore the rest later.
export default function FilterBar({ options, value, onChange }: Props) {
  const units = options?.units ?? [];
  // The Predictive Analysis page plans from the latest stock snapshot, so Period and
  // Department do not apply there: only Unit and Product Group are shown on that page.
  const predictive = usePathname()?.startsWith("/predictive-analysis") ?? false;
  const set = (patch: Partial<FilterState>) => onChange({ ...value, ...patch });

  const cls =
    "w-full rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-sm " +
    "text-slate-700 focus:border-accent focus:outline-none";
  const label = "mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500";

  const isFiltered =
    value.unit !== "All" || value.stock_take_group !== "All" ||
    (!predictive && value.department !== "All");

  return (
    <div className="flex w-full items-end gap-4">
      <div className={`grid min-w-0 flex-1 gap-4 ${predictive ? "grid-cols-2" : "grid-cols-4"}`}>
        <div className="min-w-0">
          <label className={label}>Unit</label>
          <select className={cls} value={value.unit}
                  onChange={(e) => set({ unit: e.target.value })}>
            <option value="All">All Units</option>
            {units.map((u) => (
              <option key={u.Unit_ID} value={u.Unit_ID}>
                {u.Unit_Name} ({u.Unit_ID})
              </option>
            ))}
          </select>
        </div>
        {!predictive && <div className="min-w-0">
          <label className={label}>Period</label>
          <select className={cls} value={value.preset}
                  onChange={(e) => set({ preset: e.target.value })}>
            {options?.presets.map((p) => (
              <option key={p} value={p}>{PRESET_LABELS[p] ?? p}</option>
            ))}
          </select>
        </div>}
        <div className="min-w-0">
          <label className={label}>Product Group</label>
          <select className={cls} value={value.stock_take_group}
                  onChange={(e) => set({ stock_take_group: e.target.value })}>
            <option value="All">All Groups</option>
            {options?.stock_take_groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        {!predictive && <div className="min-w-0">
          <label className={label}>Department</label>
          <select className={cls} value={value.department}
                  onChange={(e) => set({ department: e.target.value })}>
            <option value="All">All Departments</option>
            {options?.departments.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>}
      </div>
      {isFiltered && (
        <button className="shrink-0 pb-2 text-xs text-brand underline hover:text-brand-dark"
                onClick={() => onChange({
                  ...value, unit: "All", stock_take_group: "All",
                  // Department is not on the Predictive page, so Clear all must not reset it there.
                  ...(predictive ? {} : { department: "All" }),
                })}>
          Clear all
        </button>
      )}
    </div>
  );
}
