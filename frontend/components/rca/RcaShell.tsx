"use client";

// Small building blocks shared by the RCA screens: breadcrumbs, buttons, status badge,
// the controls bar (metric / month / compare / view) and a modal.

import type { ReactNode } from "react";
import { flagMeta } from "@/lib/rca-format";
import type { EntityFlag, LensInfo, RcaOptions, RowTone } from "@/lib/rca-types";

export const panel = "rounded-lg border border-slate-200 bg-white shadow-sm";
export const btn = "inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-[13px] font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
export const btnPrimary = "inline-flex items-center gap-1.5 rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";

export interface Crumb { label: string; onClick?: () => void }

export function Crumbs({ items, right }: { items: Crumb[]; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[13px]">
      <span className="font-semibold text-accent">RCA</span>
      <span className="font-semibold text-slate-900">Platform</span>
      {items.map((c, i) => (
        <span key={i} className="flex items-center gap-2">
          <span className="text-slate-400">›</span>
          {c.onClick
            ? <button type="button" onClick={c.onClick} className="rounded bg-slate-100 px-2.5 py-0.5 text-slate-600 hover:bg-slate-200">{c.label}</button>
            : <span className="rounded bg-slate-100 px-2.5 py-0.5 font-medium text-slate-900">{c.label}</span>}
        </span>
      ))}
      {right && <div className="ml-auto flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

export function StatusBadge({ flag, tone, className = "" }: { flag?: EntityFlag; tone?: RowTone; className?: string }) {
  const m = flagMeta(flag, tone);
  return (
    <span title={m.hint}
          className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded px-2 py-0.5 text-[10.5px] font-bold tracking-wide ring-1 ring-inset ${m.chip} ${className}`}>
      <i className={`inline-block h-1.5 w-1.5 rounded-full ${m.dot}`} />{m.text}
    </span>
  );
}

/** A row of exclusive choices (metric, comparison ...). `inline` puts the label to the left to save height. */
export function Segmented<T extends string>({
  value, options, onChange, label, inline = false,
}: { value: T; options: { key: T; label: string; disabled?: boolean; title?: string }[]; onChange: (k: T) => void; label: string; inline?: boolean }) {
  return (
    <div className={inline ? "flex items-center gap-2" : ""}>
      <p className={`${inline ? "" : "mb-1 "}whitespace-nowrap text-[10.5px] font-semibold uppercase tracking-wide text-slate-500`}>{label}</p>
      <div className="inline-flex flex-wrap gap-0.5 rounded-md border border-slate-200 bg-slate-50 p-0.5">
        {options.map((o) => (
          <button key={o.key} type="button" disabled={o.disabled} title={o.title} aria-pressed={value === o.key}
                  onClick={() => onChange(o.key)}
                  className={`rounded px-2.5 py-1 text-[12.5px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    value === o.key ? "bg-nav text-white shadow-sm" : "text-slate-700 hover:bg-white"}`}>{o.label}</button>
        ))}
      </div>
    </div>
  );
}

// Views shown as buttons, in this order, when the metric has them. Anything else is under "More views".
// This is only an ORDER of preference: which views exist at all comes from the backend per metric.
const PRIMARY_VIEWS = ["region", "unit", "department", "doctor", "payer", "item", "store", "category"];

export interface ControlsProps {
  options: RcaOptions;
  metric: string; month: string; compare: string; lensKey: string;
  views: LensInfo[] | null;                     // the loaded lens's list (with counts), else null
  onMetric: (k: string) => void; onMonth: (m: string) => void; onCompare: (k: string) => void; onLens: (k: string) => void;
  compareOk: (k: string) => boolean;
}

export function Controls(p: ControlsProps) {
  const metric = p.options.metrics.find((m) => m.key === p.metric)!;
  const months = p.options.months;
  const idx = months.findIndex((m) => m.value === p.month);
  const views: LensInfo[] = p.views ?? metric.dims.map((d) => ({ key: d.key, label: d.label, segments: -1 }));
  const primary = PRIMARY_VIEWS.map((k) => views.find((v) => v.key === k)).filter(Boolean) as LensInfo[];
  const more = views.filter((v) => !primary.some((x) => x.key === v.key));
  const moreActive = more.some((v) => v.key === p.lensKey);

  const lab = "whitespace-nowrap text-[10.5px] font-semibold uppercase tracking-wide text-slate-500";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Segmented inline label="Metric" value={p.metric} onChange={p.onMetric}
                   options={p.options.metrics.map((m) => ({ key: m.key, label: m.label, title: m.definition }))} />
        <div className="flex items-center gap-2">
          <p className={lab}>Month</p>
          <div className="inline-flex items-center gap-1">
            <button type="button" aria-label="Previous month" disabled={idx <= 0} onClick={() => p.onMonth(months[idx - 1].value)} className={`${btn} px-2 py-1`}>‹</button>
            <select value={p.month} onChange={(e) => p.onMonth(e.target.value)}
                    className="rounded-md border border-slate-300 bg-white px-2 py-1 text-[12.5px] font-medium text-slate-800 focus:border-accent focus:outline-none">
              {[...months].reverse().map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            <button type="button" aria-label="Next month" disabled={idx < 0 || idx >= months.length - 1} onClick={() => p.onMonth(months[idx + 1].value)} className={`${btn} px-2 py-1`}>›</button>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Segmented inline label="Compare" value={p.compare} onChange={p.onCompare}
                   options={metric.compares.map((c) => ({
                     key: c.key, label: c.label, disabled: !p.compareOk(c.key),
                     title: p.compareOk(c.key) ? undefined : "No data for that comparison in this month",
                   }))} />
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`${lab} mr-0.5`}>View by</span>
          {primary.map((v) => {
            const one = v.segments >= 0 && v.segments < 2;
            return (
              <button key={v.key} type="button" disabled={one} aria-pressed={p.lensKey === v.key}
                      title={one ? `Only one ${v.label.toLowerCase()} in the current top-bar filters` : undefined}
                      onClick={() => p.onLens(v.key)}
                      className={`rounded-full border px-2.5 py-0.5 text-[12.5px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
                        p.lensKey === v.key ? "border-brand bg-brand text-white" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
                {v.label}{v.segments >= 2 && <span className={`ml-1 text-[11px] ${p.lensKey === v.key ? "text-white/80" : "text-slate-400"}`}>{v.segments}</span>}
              </button>
            );
          })}
          {more.length > 0 && (
            <select value={moreActive ? p.lensKey : ""} onChange={(e) => e.target.value && p.onLens(e.target.value)} aria-label="More views"
                    className={`rounded-full border px-2.5 py-0.5 text-[12.5px] font-medium focus:outline-none ${
                      moreActive ? "border-brand bg-brand text-white" : "border-slate-300 bg-white text-slate-700"}`}>
              <option value="">More views…</option>
              {more.map((v) => <option key={v.key} value={v.key} disabled={v.segments >= 0 && v.segments < 2}>{v.label}{v.segments >= 2 ? ` (${v.segments})` : ""}</option>)}
            </select>
          )}
        </div>
      </div>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-3xl rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <button type="button" onClick={onClose} className={btn}>Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ErrorBox({ message, onBack }: { message: string; onBack?: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <span>{message}</span>
      {onBack && <button type="button" onClick={onBack} className={btn}>← Back</button>}
    </div>
  );
}
