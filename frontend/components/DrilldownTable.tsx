"use client";

import { inrCompact } from "@/lib/format";

export interface DrillColumn {
  key: string;          // key in each row
  label: string;        // header text
  color?: string;       // small colour chip before the header (matches the chart's series)
}

type Row = Record<string, string | number>;

// A drill-down shown as a table: a label column followed by value columns (rupees,
// shown in Cr like the rest of the dashboards). Same look as DrilldownModal /
// DrilldownUnitModal. Used by the Stock Ageing drill-down and, in two levels, by the
// Expiry Risk drill-down (click a row -> onRowClick; "Back" -> onBack).
export default function DrilldownTable({
  title, labelKey, labelHeader, columns, rows, onClose, onRowClick, onBack, hint,
}: {
  title: string;
  labelKey: string;
  labelHeader: string;
  columns: DrillColumn[];
  rows: Row[];
  onClose: () => void;
  onRowClick?: (row: Row) => void;
  onBack?: () => void;
  hint?: string;
}) {
  const totals = columns.map((c) => rows.reduce((s, r) => s + Number(r[c.key] ?? 0), 0));
  const clickable = !!onRowClick;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
           className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between rounded-t-lg bg-nav px-5 py-3">
          <div className="flex min-w-0 items-center gap-3">
            {onBack && (
              <button type="button" onClick={onBack}
                      className="shrink-0 rounded bg-white/15 px-2 py-0.5 text-xs text-white hover:bg-white/25">
                &larr; Back
              </button>
            )}
            <h3 className="truncate text-sm font-semibold text-white">{title}</h3>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
                  className="text-white/80 hover:text-white">&#10005;</button>
        </div>
        {hint && <p className="border-b border-slate-100 bg-canvas px-5 py-1.5 text-xs text-slate-500">{hint}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0">
              <tr className="bg-canvas text-nav">
                <th className="px-5 py-2 text-left font-medium">{labelHeader}</th>
                {columns.map((c) => (
                  <th key={c.key} className="px-4 py-2 text-right font-medium">
                    {c.color && (
                      <span aria-hidden className="mr-1.5 inline-block h-2 w-2 rounded-sm align-middle"
                            style={{ background: c.color }} />
                    )}
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={columns.length + 1} className="px-5 py-6 text-center text-slate-500">No data</td></tr>
              )}
              {rows.map((r) => (
                <tr key={String(r[labelKey])}
                    onClick={clickable ? () => onRowClick!(r) : undefined}
                    onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRowClick!(r); } } : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    className={`border-t border-slate-100 ${clickable ? "cursor-pointer hover:bg-canvas focus:bg-canvas focus:outline-none" : ""}`}>
                  <td className="px-5 py-2 text-slate-900">{String(r[labelKey])}</td>
                  {columns.map((c) => (
                    <td key={c.key} className="px-4 py-2 text-right font-medium text-nav">
                      {inrCompact(Number(r[c.key] ?? 0))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            {rows.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-slate-200 bg-canvas font-semibold text-nav">
                  <td className="px-5 py-2">Total</td>
                  {totals.map((t, i) => <td key={columns[i].key} className="px-4 py-2 text-right">{inrCompact(t)}</td>)}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
        <div className="flex justify-end border-t border-slate-100 px-5 py-3">
          <button type="button" onClick={onClose}
                  className="rounded bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand-dark">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
