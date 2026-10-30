"use client";

import { useState } from "react";
import { fmtDelta, fmtValue } from "@/lib/rca-format";
import type { RcaFmt, RcaTree, TreeFlag, TreeNode } from "@/lib/rca-types";
import { PatternTag, card, h2, sub } from "./RcaParts";

const FLAG_STYLE: Record<TreeFlag, string> = {
  deviating: "bg-red-50 text-red-800 ring-red-200",
  watch: "bg-amber-50 text-amber-800 ring-amber-200",
  normal: "bg-slate-100 text-slate-600 ring-slate-200",
  minor: "bg-slate-50 text-slate-400 ring-slate-200",
  no_history: "bg-slate-50 text-slate-500 ring-slate-200",
};
const FLAG_TEXT: Record<TreeFlag, string> = {
  deviating: "Deviating", watch: "Watch", normal: "Normal", minor: "Minor", no_history: "No history",
};

function FlagBadge({ f, why }: { f: TreeFlag; why?: string }) {
  return <span title={why} className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${FLAG_STYLE[f]}`}>{FLAG_TEXT[f]}</span>;
}

function whyFlag(n: TreeNode, material: number): string {
  if (n.flag === "minor") return `Explains under ${material}% of the change, so it is not assessed`;
  const e = n.evidence;
  if (!e.available) return e.reason ?? "No history";
  return `Its ${e.basis} is ${Math.abs(e.z ?? 0).toFixed(1)} standard deviations ${(e.z ?? 0) >= 0 ? "above" : "below"} normal over ${e.n} other months`;
}

function Branch({
  node, depth, kpiFmt, higherIs, selected, onSelect, onPath, material,
}: {
  node: TreeNode; depth: number; kpiFmt: RcaFmt; higherIs: string; selected: string; onSelect: (id: string) => void;
  onPath: Set<string>; material: number;
}) {
  const [open, setOpen] = useState(true);
  const has = node.children.length > 0;
  const bad = node.impact == null ? null : higherIs === "better" ? node.impact < 0 : higherIs === "worse" ? node.impact > 0 : null;
  const impactCls = node.kind === "kpi" ? "text-slate-900" : bad === null ? "text-slate-900" : bad ? "text-red-700" : "text-emerald-700";
  return (
    <div className={depth ? "ml-5 border-l border-slate-200 pl-3" : ""}>
      <div onClick={() => onSelect(node.id)}
           className={`my-1.5 flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 transition hover:bg-slate-50 ${
             selected === node.id ? "border-brand bg-red-50/40" : onPath.has(node.id) ? "border-slate-400 bg-white" : "border-slate-200 bg-white"}`}>
        <button type="button" aria-label={open ? "Collapse" : "Expand"}
                onClick={(e) => { e.stopPropagation(); if (has) setOpen(!open); }}
                className={`h-5 w-5 shrink-0 rounded text-xs ${has ? "text-slate-600 hover:bg-slate-200" : "invisible"}`}>{open ? "▾" : "▸"}</button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold text-slate-900">
            {node.label}{onPath.has(node.id) && node.kind !== "kpi" && <span className="ml-2 rounded bg-nav px-1.5 py-0.5 text-[10px] font-semibold text-white">MAIN PATH</span>}
          </p>
          {node.kind === "quantity" && node.fmt && (
            <p className="text-[11px] text-slate-500">{fmtValue(node.fmt, node.current)} now · {fmtValue(node.fmt, node.base)} before ({fmtDelta(node.fmt, node.change)})</p>
          )}
          {node.kind === "kpi" && <p className="text-[11px] text-slate-500">{fmtValue(kpiFmt, node.current)} now · {fmtValue(kpiFmt, node.base)} before</p>}
          {node.kind === "effect" && <p className="text-[11px] text-slate-500">{node.how}</p>}
        </div>
        <div className="text-right">
          <p className={`text-sm font-bold tabular-nums ${impactCls}`}>{fmtDelta(kpiFmt, node.impact)}</p>
          {node.kind !== "kpi" && node.share_pct != null && <p className="text-[11px] text-slate-500">{node.share_pct.toFixed(0)}% of the change</p>}
        </div>
        {node.kind !== "kpi" && <FlagBadge f={node.flag} why={whyFlag(node, material)} />}
      </div>
      {open && node.children.map((c) => (
        <Branch key={c.id} node={c} depth={depth + 1} kpiFmt={kpiFmt} higherIs={higherIs}
                selected={selected} onSelect={onSelect} onPath={onPath} material={material} />
      ))}
    </div>
  );
}

function find(n: TreeNode, id: string): TreeNode | null {
  if (n.id === id) return n;
  for (const c of n.children) { const r = find(c, id); if (r) return r; }
  return null;
}

export default function RcaTreeView({ data }: { data: RcaTree }) {
  const root = data.tree, kpiFmt = data.metric.fmt;
  const [selected, setSelected] = useState<string>(data.chain.length > 1 ? data.chain[data.chain.length - 1].id.split(":")[0] : "root");
  const [dimKey, setDimKey] = useState<string | null>(null);
  const node = find(root, selected) ?? root;
  const onPath = new Set(data.chain.map((c) => c.id.split(":")[0]));
  const split = node.splits.find((s) => s.key === dimKey) ?? node.splits[0];
  const material = data.thresholds.material_share_pct;

  return (
    <div className="space-y-4">
      <div className={card}>
        <h2 className={h2}>What the tree says</h2>
        <ul className="mt-2 space-y-1.5 text-[15px] leading-relaxed text-slate-800">
          {data.narrative.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="font-semibold uppercase tracking-wide text-slate-500">Main path</span>
          {data.chain.map((c, i) => (
            <span key={c.id} className="flex items-center gap-2">
              <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 font-semibold text-slate-800">
                {c.label}{i > 0 && <> · {fmtDelta(kpiFmt, c.impact)}{c.share_pct != null ? ` (${c.share_pct.toFixed(0)}%)` : ""}</>}
              </span>
              {i < data.chain.length - 1 && <span className="text-slate-400">›</span>}
            </span>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-slate-500">
          {data.reconciliation.ok ? "✔ The branches add up exactly to the change in the KPI." : `⚠ The branches differ from the total by ${data.reconciliation.max_gap}.`}
          {" "}A branch is judged only if it explains at least {material}% of the change; “Deviating” means its own move is unusual against its other months.
          “How the KPI is built” is a business definition; check it with the client.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className={card}>
          <h2 className={h2}>How {data.metric.label.toLowerCase()} is built</h2>
          <p className={sub}>{root.how}. Each branch shows how much of the KPI’s change it accounts for. Click a branch for its breakdown.</p>
          <div className="mt-3"><Branch node={root} depth={0} kpiFmt={kpiFmt} higherIs={data.metric.higher_is}
                                       selected={selected} onSelect={(id) => { setSelected(id); setDimKey(null); }} onPath={onPath} material={material} /></div>
        </div>

        <div className={card}>
          <h2 className={h2}>{node.label}</h2>
          <p className={sub}>{node.kind === "kpi" ? "Pick a branch on the left to break it down." : node.how || "Part of the branch above."}</p>
          {node.kind === "effect" && (
            <p className="mt-3 text-sm text-slate-700">A calendar effect, not a quantity: it cannot be split by department, item or doctor.</p>
          )}
          {node.kind === "quantity" && node.splits.length === 0 && <p className="mt-3 text-sm text-slate-500">No breakdown is available for this branch.</p>}
          {node.splits.length > 0 && split && (
            <>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {node.splits.map((s) => (
                  <button key={s.key} type="button" onClick={() => setDimKey(s.key)}
                          className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${s.key === split.key ? "bg-nav text-white ring-nav" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"}`}>
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                <PatternTag p={split.pattern} />
                {split.top1_share_pct != null && <span>top contributor explains {split.top1_share_pct.toFixed(0)}% of the KPI’s change</span>}
              </div>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead className="text-[11px] uppercase tracking-wide text-slate-500">
                    <tr><th className="py-2 pr-2">{split.label}</th><th className="pr-2 text-right">Impact</th><th className="pr-2 text-right">Share</th>
                      <th className="pr-2 text-right">Now → before</th><th>Assessment</th></tr>
                  </thead>
                  <tbody>
                    {split.rows.map((r) => (
                      <tr key={r.segment} className="border-t border-slate-100">
                        <td className="py-2 pr-2 font-semibold text-slate-900">{r.segment}</td>
                        <td className="pr-2 text-right font-semibold tabular-nums">{fmtDelta(kpiFmt, r.impact)}</td>
                        <td className="pr-2 text-right tabular-nums">{r.share_pct != null ? `${r.share_pct.toFixed(0)}%` : "–"}</td>
                        <td className="pr-2 text-right tabular-nums text-slate-600">{fmtValue("currency", r.current)} → {fmtValue("currency", r.base)}</td>
                        <td><FlagBadge f={r.flag} why={r.evidence.available ? `${r.evidence.basis}: ${Math.abs(r.evidence.z ?? 0).toFixed(1)} standard deviations ${(r.evidence.z ?? 0) >= 0 ? "above" : "below"} normal` : r.evidence.reason} /></td>
                      </tr>
                    ))}
                    {split.other && (
                      <tr className="border-t border-slate-100 text-slate-500"><td className="py-2 pr-2">{split.other.label}</td>
                        <td className="pr-2 text-right tabular-nums">{fmtDelta(kpiFmt, split.other.impact)}</td><td colSpan={3} /></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
