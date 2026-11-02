"use client";

import { useState } from "react";
import DrilldownTable from "./DrilldownTable";

type Row = Record<string, string | number>;

const COLUMNS = [
  { key: "Near Expiry", label: "Near Expiry", color: "#e08a1e" },
  { key: "Expiry", label: "Expiry", color: "#c0392b" },
];

// Expiry Risk Trend double drill-down.
//   click a month's bar  -> table of Unit | Near Expiry | Expiry
//   click anywhere in a unit's row -> table of Department | Near Expiry | Expiry for that unit
// Both levels come from the chart's one drilldown dictionary: "Jan 26" holds the units,
// "Jan 26|<unit>" holds that unit's departments (see metrics.expiry_by_unit_and_dept).
export default function ExpiryDrilldown({ month, drilldown, onClose }: {
  month: string;
  drilldown: Record<string, Row[]>;
  onClose: () => void;
}) {
  const [unit, setUnit] = useState<string | null>(null);

  if (unit) {
    return (
      <DrilldownTable
        title={`Expiry Risk by Department \u2014 ${unit} \u2014 ${month}`}
        labelKey="Department" labelHeader="Department" columns={COLUMNS}
        rows={drilldown[`${month}|${unit}`] ?? []}
        onBack={() => setUnit(null)} onClose={onClose} />
    );
  }
  return (
    <DrilldownTable
      title={`Expiry Risk by Unit \u2014 ${month}`}
      labelKey="Unit" labelHeader="Unit" columns={COLUMNS}
      rows={drilldown[month] ?? []}
      hint="Click a unit to see its departments"
      onRowClick={(r) => setUnit(String(r.Unit))}
      onClose={onClose} />
  );
}
