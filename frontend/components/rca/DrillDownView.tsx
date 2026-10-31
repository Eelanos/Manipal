"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchRcaAnalysis } from "@/lib/rca-api";
import { fmtDelta, fmtValue } from "@/lib/rca-format";
import type { FilterState } from "@/lib/types";
import type { RcaAnalysis } from "@/lib/rca-types";
import { btn, btnPrimary, Crumbs, ErrorBox, panel, StatusBadge } from "./RcaShell";

interface Params { metric: string; month: string; compare: string }

// "Who caused it?" - tabs per view, every segment of the slice listed, any row can be drilled into.
export default function DrillDownView({
  params, filters, initialPath, hasTree, onHome, onBack, onTree,
}: {
  params: Params; filters: FilterState; initialPath: string[]; hasTree: boolean;
  onHome: () => void; onBack: () => void; onTree: (path: string[]) => void;
}) {
  const [path, setPath] = useState<string[]>(initialPath);
  const [data, setData] = useState<RcaAnalysis | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<string | null>(null);

  useEffect(() => { setPath(initialPath); }, [initialPath.join("|")]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true); setErr(null);
    fetchRcaAnalysis(params, filters, path, ac.signal, true)
      .then((d) => { setData(d); })
      .catch((e) => { if (e.name !== "AbortError") setErr(String(e.message ?? e)); })
      .finally(() => { if (!ac.signal.aborted) setLoading(false); });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.metric, params.month, params.compare, filters, path.join("|")]);

  // Tabs: the most concentrated view first.
  const dims = useMemo(() => {
    if (!data) return [];
    const best = (d: RcaAnalysis["dimensions"][number]) => Math.max(...d.rows.map((r) => r.share_of_slice_pct ?? r.share_pct ?? -1), -1);
    return [...data.dimensions].sort((a, b) => best(b) - best(a));
  }, [data]);
  const active = dims.find((d) => d.key === tab) ?? dims[0];
  useEffect(() => { setTab(null); }, [path.join("|")]);              // eslint-disable-line react-hooks/exhaustive-deps

  const m = data?.metric;
  const fmt = m?.fmt ?? "percent";
  const last = path.length ? path[path.length - 1].split(":")[1] : "";
  const th = "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500";

  return (
    <div className="flex h-[calc(100vh-128px)] min-h-[34rem] flex-col gap-2.5">
      <Crumbs items={[{ label: "Home", onClick: onHome }, { label: "Back", onClick: onBack }, { label: "Drill-down" }]} />
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-semibold leading-tight text-slate-900">Drill-down analysis</h1>
          <p className="truncate text-[13px] text-slate-500">
            {data ? `${data.metric.label} · ${data.period.label} vs ${data.compare.label}` : ""}{last ? ` · inside ${path.map((p) => p.split(":")[1]).join(" › ")}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {path.length > initialPath.length && <button type="button" className={btn} onClick={() => setPath(path.slice(0, -1))}>Step up</button>}
          <button type="button" className={btn} onClick={onBack}>← Back</button>
          <button type="button" className={btnPrimary} disabled={!hasTree} onClick={() => onTree(path)}
                  title={hasTree ? undefined : "KPI trees exist for Formulary compliance and Inventory days"}>KPI tree →</button>
        </div>
      </div>

      {data && (
        <div className={`${panel} flex shrink-0 flex-wrap items-center gap-2 px-3.5 py-2`}>
          {data.chain.map((c, i) => (
            <span key={i} className="flex items-center gap-2">
              <button type="button" disabled={i === data.chain.length - 1} onClick={() => setPath(path.slice(0, i))}
                      className={`rounded-md border px-3 py-1 text-left ${i === data.chain.length - 1 ? "border-brand bg-red-50/50" : "border-slate-200 bg-slate-50 hover:bg-slate-100"}`}>
                <span className="block text-[10.5px] font-semibold uppercase tracking-wide text-slate-500">{i === 0 ? "Whole scope" : `Step ${i}`}</span>
                <span className="block text-[13px] font-semibold text-slate-900">{c.label}</span>
                <span className="block text-[12px] font-bold text-slate-800">{fmtDelta(fmt, c.contribution)}
                  {c.share_pct != null && i > 0 && <span className="ml-1.5 font-semibold text-brand">{c.share_pct.toFixed(0)}%</span>}</span>
              </button>
              {i < data.chain.length - 1 && <span className="text-lg text-slate-400">›</span>}
            </span>
          ))}
          <span className="ml-auto text-[11.5px] text-slate-500">Click a step to go back to it</span>
        </div>
      )}

      {err && <ErrorBox message={err} onBack={onBack} />}
      {!err && (
        <div className={`${panel} flex min-h-0 flex-1 flex-col overflow-hidden transition-opacity ${loading ? "opacity-50" : ""}`}>
          {!data ? <div className="h-72 animate-pulse bg-slate-100" /> : (
            <>
              <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-200 bg-slate-50 px-2 py-1.5">
                {dims.map((d) => (
                  <button key={d.key} type="button" aria-pressed={active?.key === d.key} onClick={() => setTab(d.key)}
                          className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium ${active?.key === d.key ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:bg-white/70"}`}>
                    {d.label}<span className="rounded bg-accent px-1.5 text-[11px] font-semibold text-white">{d.segments}</span>
                  </button>
                ))}
              </div>
              {active ? (
                <div className="min-h-0 flex-1 overflow-auto">
                  <table className="w-full text-[13px]">
                    <thead className="sticky top-0 z-10 bg-white">
                      <tr>
                        <th className={th}>{active.label}</th><th className={`${th} text-right`}>Part of the change</th>
                        <th className={`${th} text-right`}>Share of this slice</th><th className={`${th} text-right`}>Now → {data.compare.label}</th>
                        <th className={`${th} text-right`}>{data.metric.weight_label || "Size"}</th><th className={th}>Status</th><th className={th} />
                      </tr>
                    </thead>
                    <tbody>
                      {active.rows.map((r) => (
                        <tr key={r.segment} className="border-t border-slate-100 hover:bg-slate-50">
                          <td className="max-w-[18rem] truncate px-3 py-2 font-semibold text-slate-900" title={r.segment}>
                            {r.segment}
                            {r.parts && <span className="block text-[11px] font-normal text-slate-500">{Object.entries(r.parts).map(([k, v]) => `${k} ${fmtDelta(fmt, v)}`).join(" · ")}</span>}
                          </td>
                          <td className={`px-3 py-2 text-right font-semibold tabular-nums ${r.tone === "bad" ? "text-red-700" : r.tone === "good" ? "text-emerald-700" : "text-slate-900"}`}>{fmtDelta(fmt, r.contribution)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-slate-600">{r.share_of_slice_pct != null ? `${r.share_of_slice_pct.toFixed(0)}%` : "–"}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-slate-600">{fmtValue(fmt, r.own_current)} → {fmtValue(fmt, r.own_base)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-slate-600">{r.weight_in_slice_pct != null ? `${r.weight_in_slice_pct.toFixed(0)}%` : r.weight_pct != null ? `${r.weight_pct.toFixed(0)}%` : "–"}</td>
                          <td className="px-3 py-2"><StatusBadge flag={r.flag} tone={r.tone} /></td>
                          <td className="px-3 py-2 text-right"><button type="button" className={btn} onClick={() => setPath([...path, `${active.key}:${r.segment}`])}>Drill in</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="p-6 text-sm text-slate-500">Nothing further to split here.</p>}
            </>
          )}
        </div>
      )}

      {data && (
        <p className="shrink-0 text-[11px] leading-snug text-slate-500">
          “Part of the change” adds up exactly to {fmtDelta(fmt, data.slice_total ?? null)} for this slice in every tab.
          “Share of this slice” compares it with {last ? last : "the whole scope"}’s own change; “Size” is how big the segment is inside the slice, so a share far above its size is the interesting one.
          Not available here: {data.unavailable_dimensions.length ? data.unavailable_dimensions.map((u) => u.label.toLowerCase()).join(", ") : "none"}.
        </p>
      )}

    </div>
  );
}
