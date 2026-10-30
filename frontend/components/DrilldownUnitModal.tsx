"use client";

import { inrCompact } from "@/lib/format";

interface Row {
  Unit: string;
  Stock: number;
  "Inventory Days": number;
}

// Drill-down for the Consumption Trend chart: one row per unit with its stock
// value and inventory days for the clicked month. Same look as DrilldownModal.
export default function DrilldownUnitModal({
  title, rows, onClose,
}: { title: string; rows: Row[]; onClose: () => void }) {
  const totalStock = rows.reduce((sum, r) => sum + r.Stock, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between bg-nav px-5 py-3 rounded-t-lg">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-white/80 hover:text-white">✕</button>
        </div>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-canvas text-nav">
                <th className="px-5 py-2 text-left font-medium">Unit</th>
                <th className="px-5 py-2 text-right font-medium">Stock</th>
                <th className="px-5 py-2 text-right font-medium">Inventory Days</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.Unit} className="border-t border-slate-100">
                  <td className="px-5 py-2 text-slate-900">{r.Unit}</td>
                  <td className="px-5 py-2 text-right font-medium text-nav">
                    {inrCompact(r.Stock)}
                  </td>
                  <td className="px-5 py-2 text-right font-medium text-nav">
                    {r["Inventory Days"].toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3">
          <span className="text-sm font-semibold text-nav">
            Total Stock: {inrCompact(totalStock)}
          </span>
          <button onClick={onClose}
                  className="rounded bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand-dark">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
