"use client";

import { useMemo, useState } from "react";
import { formatCell } from "@/lib/format";
import type { TableData } from "@/lib/types";

const PAGE_SIZE = 15;

export default function DataTable({ table }: { table: TableData }) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [asc, setAsc] = useState(false);
  const [page, setPage] = useState(0);

  const rows = useMemo(() => {
    let r = table.rows;
    if (query) {
      const q = query.toLowerCase();
      r = r.filter((row) =>
        Object.values(row).some((v) => String(v).toLowerCase().includes(q)));
    }
    if (sortKey) {
      r = [...r].sort((a, b) => {
        const x = a[sortKey], y = b[sortKey];
        if (typeof x === "number" && typeof y === "number") return asc ? x - y : y - x;
        return asc
          ? String(x).localeCompare(String(y))
          : String(y).localeCompare(String(x));
      });
    }
    return r;
  }, [table.rows, query, sortKey, asc]);

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleSort = (key: string) => {
    if (sortKey === key) setAsc(!asc);
    else { setSortKey(key); setAsc(false); }
    setPage(0);
  };

  if (!table.columns.length) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-200 p-3">
        <input
          className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-accent focus:outline-none"
          placeholder="Search..."
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(0); }}
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              {table.columns.map((c) => (
                <th key={c.key} onClick={() => toggleSort(c.key)}
                    className="cursor-pointer px-4 py-2 text-left font-medium text-slate-600 hover:bg-slate-100">
                  {c.label}
                  {sortKey === c.key ? (asc ? " (asc)" : " (desc)") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                {table.columns.map((c) => (
                  <td key={c.key} className="px-4 py-2 text-slate-700">
                    {formatCell(row[c.key], c.type)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between border-t border-slate-200 p-3 text-sm">
        <span className="text-slate-500">{rows.length} rows</span>
        <div className="flex items-center gap-2">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}
                  className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40">
            Prev
          </button>
          <span className="text-slate-600">{page + 1} / {pageCount}</span>
          <button disabled={page >= pageCount - 1} onClick={() => setPage(page + 1)}
                  className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40">
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
