"use client";

import { useMemo, useState } from "react";
import { fmtDelta, fmtValue, flagMeta } from "@/lib/rca-format";
import type { EntityFlag, RcaLens, RcaOptions } from "@/lib/rca-types";
import { btn, Controls, type ControlsProps, Crumbs, ErrorBox, Modal, panel, StatusBadge } from "./RcaShell";

type Sort = "impact" | "name" | "status";
const STATUS: { key: "all" | EntityFlag; label: string }[] = [
  { key: "all", label: "All statuses" }, { key: "deviating", label: "High" }, { key: "watch", label: "Medium" },
  { key: "normal", label: "Normal" }, { key: "minor", label: "Minor" },
];

export default function FindingsExplorer({
  options, controls, lens, loading, error, onOpenEntity, onHome,
}: {
  options: RcaOptions; controls: ControlsProps; lens: RcaLens | null; loading: boolean; error: string | null;
  onOpenEntity: (segment: string) => void; onHome: () => void;
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"all" | EntityFlag>("all");
  const [sort, setSort] = useState<Sort>("impact");
  const [showRule, setShowRule] = useState(false);

  const rows = useMemo(() => {
    if (!lens) return [];
    let r = lens.entities.filter((e) => e.segment.toLowerCase().includes(q.trim().toLowerCase()));
    if (status !== "all") r = r.filter((e) => e.flag === status);
    // "impact" keeps the backend order: the ones that hurt the KPI most first.
    if (sort === "name") r = [...r].sort((a, b) => a.segment.localeCompare(b.segment));
    if (sort === "status") r = [...r].sort((a, b) => flagMeta(a.flag, a.tone).rank - flagMeta(b.flag, b.tone).rank);
    return r;
  }, [lens, q, status, sort]);

  const fmt = lens?.metric.fmt ?? "percent";
  const th = "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500";

  return (
    <div className="flex h-[calc(100vh-128px)] min-h-[34rem] flex-col gap-2.5">
      <Crumbs items={[{ label: "Home", onClick: onHome }, { label: "Findings explorer" }]}
              right={<span className="text-[13px] text-slate-500">{rows.length} of {lens?.summary.count ?? 0} {lens?.lens.label.toLowerCase()}s</span>} />
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[20px] font-semibold text-slate-900">Findings explorer</h1>
        <p className="text-[13px] text-slate-500">Browse, filter and investigate every {lens?.lens.label.toLowerCase() ?? "entity"}.</p>
      </div>
      <div className={`${panel} px-3.5 py-2.5`}><Controls {...controls} views={lens?.lenses ?? null} /></div>

      <div className="flex flex-wrap gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${lens?.lens.label.toLowerCase() ?? ""}s…`}
               className="min-w-[14rem] flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-[13px] focus:border-accent focus:outline-none" />
        <select value={status} onChange={(e) => setStatus(e.target.value as "all" | EntityFlag)} aria-label="Status"
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-[13px]">
          {STATUS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort"
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-[13px]">
          <option value="impact">Sort: hurt the KPI most first</option>
          <option value="status">Sort: status</option>
          <option value="name">Sort: name</option>
        </select>
        {options.thresholds && <button type="button" className={btn} onClick={() => setShowRule(true)}>How status is decided</button>}
      </div>

      {error && <ErrorBox message={error} onBack={onHome} />}
      {!error && (
        <div className={`${panel} flex min-h-0 flex-1 flex-col overflow-hidden transition-opacity ${loading ? "opacity-50" : ""}`}>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 z-10 bg-slate-50">
                <tr>
                  <th className={th}>{lens?.lens.label ?? "Name"}</th><th className={th}>Status</th>
                  <th className={`${th} text-right`}>Part of the change</th><th className={`${th} text-right`}>Share</th>
                  <th className={`${th} text-right`}>Now</th><th className={`${th} text-right`}>{lens?.compare.label}</th>
                  <th className={`${th} text-right`}>{lens?.metric.weight_label || "Size"}</th><th className={th} />
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.segment} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => onOpenEntity(e.segment)}>
                    <td className="max-w-[18rem] truncate px-3 py-2 font-semibold text-slate-900" title={e.segment}>{e.segment}</td>
                    <td className="px-3 py-2"><StatusBadge flag={e.flag} tone={e.tone} /></td>
                    <td className={`px-3 py-2 text-right font-semibold tabular-nums ${e.tone === "bad" ? "text-red-700" : e.tone === "good" ? "text-emerald-700" : "text-slate-900"}`}>{fmtDelta(fmt, e.contribution)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{e.share_pct != null ? `${e.share_pct.toFixed(0)}%` : "–"}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-700">{fmtValue(fmt, e.own_current)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-500">{fmtValue(fmt, e.own_base)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{e.weight_pct != null ? `${e.weight_pct.toFixed(0)}%` : "–"}</td>
                    <td className="px-3 py-2 text-right"><button type="button" className={btn} onClick={(ev) => { ev.stopPropagation(); onOpenEntity(e.segment); }}>View →</button></td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={8} className="px-3 py-10 text-center text-slate-500">{lens ? "Nothing matches these filters." : "Loading…"}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {showRule && options.thresholds && (
        <Modal title="How status is decided" onClose={() => setShowRule(false)}>
          <ul className="space-y-1.5 text-[13px] leading-relaxed text-slate-700">
            <li><b>HIGH</b> = accounts for at least {options.thresholds.material_share_pct}% of everything that moved AND its own move is unusual against its own history (over {options.thresholds.z_unusual} standard deviations).</li>
            <li><b>MEDIUM</b> = material and between {options.thresholds.z_watch} and {options.thresholds.z_unusual} standard deviations.</li>
            <li><b>NORMAL</b> = material but within its usual range. <b>MINOR</b> = a small part of the total movement. <b>NO HISTORY</b> = too few other months to judge.</li>
          </ul>
          <p className="mt-3 text-[12px] text-slate-500">These cut-offs are settings (not hard-coded in the screen), so they can be changed to match what your client considers material.</p>
        </Modal>
      )}
    </div>
  );
}
