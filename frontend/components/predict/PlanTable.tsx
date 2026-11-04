"use client";

import { useMemo, useState } from "react";
import type { LineRow } from "@/lib/predict-types";
import { statusColor, type OnPickItem } from "./shared";

export interface Col {
  key: string;
  label: string;
  align?: "left" | "right";
  render: (r: LineRow) => React.ReactNode;
  sort: (r: LineRow) => number | string;     // value used for sorting
  sortable?: boolean;                         // default true; false for action columns
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
      <i className="h-2 w-2 rounded-full" style={{ background: statusColor(status) }} />{status}
    </span>
  );
}

// Own table (not DataTable): DataTable rounds every number to an integer, which would
// hide days-of-cover and daily usage, and it has no row click or export.
export default function PlanTable({ rows, cols, onPick, pageSize = 12, total, more, emptyText }: {
  rows: LineRow[]; cols: Col[]; onPick: OnPickItem; pageSize?: number;
  total?: number; more?: boolean; emptyText: string;
}) {
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [asc, setAsc] = useState(true);
  const [page, setPage] = useState(0);

  const view = useMemo(() => {
    let r = rows;
    if (q.trim()) {
      const s = q.trim().toLowerCase();
      r = r.filter((x) => `${x.item_name} ${x.item_id} ${x.unit_name} ${x.unit_id} ${x.group} ${x.status}`.toLowerCase().includes(s));
    }
    const col = cols.find((c) => c.key === sortKey);
    if (col) {
      r = [...r].sort((a, b) => {
        const x = col.sort(a), y = col.sort(b);
        const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return asc ? c : -c;
      });
    }
    return r;
  }, [rows, cols, q, sortKey, asc]);

  const pages = Math.max(1, Math.ceil(view.length / pageSize));
  const cur = Math.min(page, pages - 1);
  const visible = view.slice(cur * pageSize, (cur + 1) * pageSize);

  const toggle = (k: string) => {
    if (sortKey === k) setAsc(!asc); else { setSortKey(k); setAsc(true); }
    setPage(0);
  };

  if (rows.length === 0) return <p className="py-10 text-center text-sm text-slate-500">{emptyText}</p>;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 pb-3">
        <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Search item, unit, status…"
               aria-label="Search table"
               className="w-64 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-accent focus:outline-none" />
        <span className="text-xs text-slate-500">{view.length.toLocaleString("en-IN")} line{view.length === 1 ? "" : "s"}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              {cols.map((c) => c.sortable === false ? (
                <th key={c.key} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium text-slate-600 ${c.align === "right" ? "text-right" : "text-left"}`}>
                  {c.label}
                </th>
              ) : (
                <th key={c.key} scope="col" aria-sort={sortKey === c.key ? (asc ? "ascending" : "descending") : "none"}
                    className={`cursor-pointer select-none whitespace-nowrap px-3 py-2 font-medium text-slate-600 hover:bg-slate-100 ${c.align === "right" ? "text-right" : "text-left"}`}
                    onClick={() => toggle(c.key)}>
                  {c.label}{sortKey === c.key ? (asc ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={`${r.unit_id}|${r.item_id}`} tabIndex={0} role="button" aria-label={`Open ${r.item_name} at ${r.unit_name}`}
                  onClick={() => onPick(r)} onKeyDown={(e) => { if (e.key === "Enter") onPick(r); }}
                  className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none">
                {cols.map((c) => (
                  <td key={c.key} className={`px-3 py-2 text-slate-700 ${c.align === "right" ? "text-right tabular-nums" : ""}`}>{c.render(r)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between pt-3 text-xs text-slate-500">
        <span>
          {more && total !== undefined ? `Showing the first ${rows.length.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} lines. ` : ""}
          Click a row for the full picture.
        </span>
        <span className="flex items-center gap-2">
          <button type="button" disabled={cur === 0} onClick={() => setPage(cur - 1)}
                  className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40">Prev</button>
          Page {cur + 1} / {pages}
          <button type="button" disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}
                  className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40">Next</button>
        </span>
      </div>
    </div>
  );
}
