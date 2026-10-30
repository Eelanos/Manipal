"use client";

import { useMemo, useState } from "react";
import { numberFull, inrFull } from "@/lib/format";
import type { ChatCell, ChatColumn, ChatTableData } from "@/lib/chat-types";
import { DownloadIcon } from "./icons";

const PREVIEW_ROWS = 10;

function fmt(v: ChatCell, col: ChatColumn): string {
  if (v === null || v === undefined || v === "") return "—";
  if (col.type === "text") return String(v);
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  switch (col.type) {
    case "currency": return inrFull(n);
    case "number": return numberFull(n);
    case "percent": return `${n.toFixed(1)}%`;
    case "decimal": return `${n > 0 ? "+" : ""}${n.toFixed(1)}`;
    default: return String(v);
  }
}

function csvCell(v: ChatCell): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Raw (unrounded-for-display) values, so an export is usable in Excel. */
export function tableToCsv(t: ChatTableData): string {
  const head = t.columns.map((c) => csvCell(c.label)).join(",");
  const body = t.rows.map((r) => t.columns.map((c) => csvCell(r[c.key])).join(","));
  if (t.totals) body.push(t.columns.map((c) => csvCell(t.totals![c.key])).join(","));
  return "﻿" + [head, ...body].join("\n");
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ChatTable({ table, title }: { table: ChatTableData; title: string }) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [asc, setAsc] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const rows = useMemo(() => {
    if (!sortKey) return table.rows;
    return [...table.rows].sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === "number" && typeof y === "number") return asc ? x - y : y - x;
      return asc ? String(x).localeCompare(String(y)) : String(y).localeCompare(String(x));
    });
  }, [table.rows, sortKey, asc]);

  const visible = showAll ? rows : rows.slice(0, PREVIEW_ROWS);
  const toggleSort = (key: string) => {
    if (sortKey === key) setAsc(!asc);
    else { setSortKey(key); setAsc(false); }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <span className="text-xs text-slate-500">
          {table.rows.length} row{table.rows.length === 1 ? "" : "s"}
          {table.truncated ? " (first rows only)" : ""}
        </span>
        <button
          type="button"
          onClick={() => download(`${title.replace(/[^\w]+/g, "_").toLowerCase() || "manipal"}.csv`, tableToCsv(table))}
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
        >
          <DownloadIcon /> Export CSV
        </button>
      </div>
      <div className={`overflow-x-auto ${showAll && rows.length > 15 ? "max-h-[26rem] overflow-y-auto" : ""}`}>
        <table className="w-full text-xs">
          <thead className={`bg-slate-50 ${showAll && rows.length > 15 ? "sticky top-0 z-10" : ""}`}>
            <tr>
              {table.columns.map((c) => (
                <th
                  key={c.key}
                  onClick={() => toggleSort(c.key)}
                  className={`cursor-pointer select-none whitespace-nowrap px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-800 ${c.type === "text" ? "text-left" : "text-right"}`}
                >
                  {c.label}{sortKey === c.key ? (asc ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <tr key={i} className="border-t border-slate-100 transition-colors hover:bg-canvas">
                {table.columns.map((c) => (
                  <td key={c.key} className={`whitespace-nowrap px-3 py-2 text-slate-800 ${c.type === "text" ? "text-left" : "text-right tabular-nums"}`}>
                    {fmt(r[c.key], c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {table.totals && (
            <tfoot className="bg-slate-50">
              <tr className="border-t-2 border-slate-300 font-semibold">
                {table.columns.map((c) => (
                  <td key={c.key} className={`whitespace-nowrap px-3 py-1.5 text-slate-900 ${c.type === "text" ? "text-left" : "text-right tabular-nums"}`}>
                    {fmt(table.totals![c.key], c)}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {rows.length > PREVIEW_ROWS && (
        <button
          type="button"
          onClick={() => setShowAll(!showAll)}
          className="w-full border-t border-slate-100 py-1.5 text-xs text-accent hover:bg-slate-50"
        >
          {showAll ? "Show fewer rows" : `Show all ${rows.length} rows`}
        </button>
      )}
    </div>
  );
}
