"use client";

import { useState } from "react";
import ChartPanel from "@/components/ChartPanel";
import KpiCard from "@/components/KpiCard";
import NavIcon from "@/components/NavIcons";
import SaveToWorkspaceModal from "@/components/SaveToWorkspaceModal";
import type { AssistantMessage, ResultBlock } from "@/lib/chat-types";
import { useSavedDashboards } from "@/lib/saved-dashboards";
import { aiKey, useWorkspaces } from "@/lib/workspaces";
import ChatTable from "./ChatTable";
import { ArrowIcon, BulbIcon, CopyIcon } from "./icons";
import RichText from "./RichText";

const NOTICE_STYLE: Record<string, string> = {
  clarify: "border-slate-300 bg-canvas text-nav",
  chat: "border-slate-200 bg-white text-slate-800",
  out_of_scope: "border-slate-200 bg-white text-slate-800",
  not_found: "border-amber-200 bg-amber-50 text-amber-900",
  failed: "border-amber-200 bg-amber-50 text-amber-900",
  error: "border-red-200 bg-red-50 text-red-800",
};

// savedId: set on the Favorites page, where the block IS one particular saved dashboard.
// In the chat each block remembers the dashboard it saved itself, so asking the same question
// again gives a fresh "Save Dashboard" button and can be saved again.
export function Block({ block, savedId }: { block: ResultBlock; savedId?: string }) {
  const [showTable, setShowTable] = useState(false);
  const { saved, add, remove } = useSavedDashboards();
  const [mineId, setMineId] = useState<string | null>(null);
  const currentId = savedId ?? mineId;
  const isSaved = !!currentId && saved.some((d) => d.id === currentId);
  const { assign, unassign } = useWorkspaces();
  const [picking, setPicking] = useState(false);     // "Save Dashboard to Workspace" dialog
  const hasChart = block.charts.length > 0;
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        {/* A chart carries the same title itself; repeating it above is just noise. */}
        {!hasChart && <h4 className="text-[13px] font-semibold text-slate-800">{block.title}</h4>}
        {block.scope.map((s) => (
          <span key={s} className="rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500 ring-1 ring-slate-200">{s}</span>
        ))}
      </div>
      {block.notes.map((n) => (
        <p key={n} className="rounded-lg bg-amber-50 px-3 py-1.5 text-[11px] leading-snug text-amber-800 ring-1 ring-amber-100">{n}</p>
      ))}
      {block.empty ? (
        <p className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-700">{block.message}</p>
      ) : (
        <>
          {block.kpis.length > 0 && (
            <div className="grid grid-cols-2 gap-3 @lg:grid-cols-3">
              {block.kpis.map((k) => <KpiCard key={k.label} kpi={k} />)}
            </div>
          )}
          {block.charts.length > 0 && (
            <div className={`grid grid-cols-1 gap-3 ${block.charts.length > 1 ? "@2xl:grid-cols-2" : ""}`}>
              {block.charts.map((c) => <ChartPanel key={c.id} spec={c} />)}
            </div>
          )}
          {/* Chart and table show the same numbers, so when there is a chart the table is
              opt-in (and still exportable); when there is no chart it is the answer. */}
          {block.table && block.table_collapsed && !showTable && (
            <button type="button" onClick={() => setShowTable(true)}
                    className="flex w-full items-center justify-between rounded-xl bg-white px-3.5 py-2.5 text-xs font-medium text-slate-600 shadow-sm ring-1 ring-slate-200 transition hover:text-brand hover:ring-brand/40">
              <span>View data table · {block.table.rows.length} row{block.table.rows.length === 1 ? "" : "s"}</span>
              <span aria-hidden>▾</span>
            </button>
          )}
          {block.table && (!block.table_collapsed || showTable) && (
            <div className="space-y-1.5">
              <ChatTable table={block.table} title={block.title} />
              {block.table_collapsed && (
                <button type="button" onClick={() => setShowTable(false)} className="text-[11px] text-slate-400 hover:text-slate-600">
                  Hide table ▴
                </button>
              )}
            </div>
          )}
          {/* Asks which workspace to save this dashboard to (click again to remove it). */}
          <div className="flex justify-end">
            <button type="button" aria-pressed={isSaved}
                    onClick={() => {
                      if (isSaved && currentId) { remove(currentId); unassign(aiKey(currentId)); setMineId(null); }
                      else setPicking(true);
                    }}
                    className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-brand-dark">
              <NavIcon name="favorites" size={14} filled={isSaved} />
              {isSaved ? "Saved" : "Save Dashboard"}
            </button>
          </div>
          {picking && (
            <SaveToWorkspaceModal
              itemTitle={block.title}
              onClose={() => setPicking(false)}
              onSave={(wsId) => {
                const id = add(block);
                setMineId(id);
                assign(aiKey(id), wsId);
                setPicking(false);
              }} />
          )}
        </>
      )}
    </section>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2 rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 shadow-sm" aria-hidden>
      <div className="h-3 w-11/12 animate-pulse rounded bg-slate-200" />
      <div className="h-3 w-4/5 animate-pulse rounded bg-slate-200" />
      <div className="h-3 w-2/3 animate-pulse rounded bg-slate-100" />
    </div>
  );
}

export function answerText(m: AssistantMessage): string {
  const n = m.narrative;
  if (!n) return m.notice?.text ?? "";
  return [n.headline, ...n.insights, ...n.recommendations.map((r) => `Next step: ${r}`)].join("\n");
}

export default function MessageView({
  message, onAsk, isLast,
}: { message: AssistantMessage; onAsk: (q: string) => void; isLast: boolean }) {
  const [copied, setCopied] = useState(false);
  const { narrative: n, notice } = message;
  const working = message.status === "working";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answerText(message));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable: ignore */ }
  };

  return (
    <div className="space-y-4">
      {notice && (
        <p className={`rounded-2xl rounded-tl-md border p-3.5 text-sm leading-relaxed shadow-sm ${NOTICE_STYLE[notice.kind] ?? NOTICE_STYLE.chat}`}>
          {notice.text}
        </p>
      )}

      {/* The written answer leads. While it is being written a placeholder holds its space. */}
      {!notice && !n && message.blocks.length > 0 && working && <Skeleton />}
      {n && (
        <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-[15px] leading-relaxed text-slate-900"><RichText text={n.headline} /></p>
          {n.insights.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {n.insights.map((t, i) => (
                <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-slate-600">
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  <span><RichText text={t} /></span>
                </li>
              ))}
            </ul>
          )}
          {n.recommendations.length > 0 && (
            <div className="mt-3 flex gap-2.5 rounded-xl bg-emerald-50 p-3 text-[13px] leading-relaxed text-emerald-900 ring-1 ring-emerald-100">
              <span className="mt-0.5 shrink-0 text-emerald-600"><BulbIcon /></span>
              <div className="space-y-1">
                {n.recommendations.map((t, i) => <p key={i}><RichText text={t} /></p>)}
              </div>
            </div>
          )}
          {!working && (
            <button type="button" onClick={copy}
                    className="mt-3 inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600">
              <CopyIcon /> {copied ? "Copied" : "Copy answer"}
            </button>
          )}
        </div>
      )}

      {message.blocks.map((b) => <Block key={b.id} block={b} />)}

      {working && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="flex gap-1" aria-hidden>
            {[0, 150, 300].map((d) => (
              <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand" style={{ animationDelay: `${d}ms` }} />
            ))}
          </span>
          {message.stage}
        </div>
      )}

      {!working && isLast && n && n.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {n.follow_ups.map((q) => (
            <button key={q} type="button" onClick={() => onAsk(q)}
                    className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-left text-xs text-slate-700 shadow-sm ring-1 ring-slate-200 transition hover:text-brand hover:ring-brand/40">
              {q} <span className="text-slate-400"><ArrowIcon /></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
