"use client";

import { useRef, useState } from "react";
import type { PlanSettings, SettingSpec } from "@/lib/predict-types";

// The three planning assumptions, editable right on the page. Limits and defaults come from the backend
// (GET /api/predict/options); the backend validates again, so this is only for a friendlier screen.
const FIELDS: { key: keyof PlanSettings; label: string }[] = [
  { key: "lead_days", label: "Delivery time" },
  { key: "buffer_days", label: "Safety buffer" },
  { key: "plan_days", label: "Order cover" },
];
const COMMIT_DELAY_MS = 700;   // wait for the user to stop typing before recalculating the page

function Field({ label, spec, value, onCommit }: {
  label: string; spec: SettingSpec; value: number; onCommit: (v: number) => void;
}) {
  const min = Number(spec.min), max = Number(spec.max);
  const [draft, setDraft] = useState(String(value));
  const [seen, setSeen] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The applied value changed from outside (Reset): show it.
  if (seen !== value) { setSeen(value); setDraft(String(value)); }

  const parsed = draft.trim() === "" ? NaN : Number(draft);
  const valid = Number.isInteger(parsed) && parsed >= min && parsed <= max;
  const clear = () => { if (timer.current) { clearTimeout(timer.current); timer.current = null; } };
  const commit = (text: string) => {
    clear();
    const n = text.trim() === "" ? NaN : Number(text);
    if (Number.isInteger(n) && n >= min && n <= max && n !== value) onCommit(n);
  };
  const change = (text: string) => {
    setDraft(text);
    clear();
    timer.current = setTimeout(() => commit(text), COMMIT_DELAY_MS);
  };
  const blur = () => {
    clear();
    if (valid) commit(draft); else setDraft(String(value));   // invalid text is discarded, the applied value stays
  };

  return (
    <label className="flex flex-col gap-1" title={spec.help}>
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <span className="flex items-center gap-2">
      <input type="number" inputMode="numeric" min={min} max={max} step={spec.step ?? 1} value={draft}
             onChange={(e) => change(e.target.value)} onBlur={blur}
             onKeyDown={(e) => { if (e.key === "Enter") { e.currentTarget.blur(); } }}
             aria-label={`${label} (${spec.unit})`} aria-invalid={!valid}
             className={`w-20 rounded-lg border-2 bg-white px-2 py-1.5 text-center text-lg font-bold tabular-nums text-slate-900 shadow-sm focus:outline-none focus:ring-2 ${
               valid ? "border-slate-400 focus:border-blue-600 focus:ring-blue-200" : "border-red-400 focus:border-red-500 focus:ring-red-200"}`} />
      <span className="text-sm font-medium text-slate-600">{spec.unit}</span>
      {!valid && <span className="text-xs font-medium text-red-600" role="alert">{min}–{max}</span>}
      </span>
    </label>
  );
}

export default function PlanControls({ specs, plan, defaults, usageMonths, onChange, onReset }: {
  specs: SettingSpec[]; plan: PlanSettings; defaults: PlanSettings; usageMonths: number | null;
  onChange: (key: keyof PlanSettings, value: number) => void; onReset: () => void;
}) {
  // Excess stock is judged against its own limit ("Excess above", default 90 days), not these three settings.
  const maxCover = specs.find((s) => s.key === "max_cover_days");
  const changed = FIELDS.some((f) => plan[f.key] !== defaults[f.key]);
  return (
    <div className="mt-3 rounded-xl border border-blue-200 border-l-4 border-l-blue-600 bg-white p-4 shadow-sm">
      <p className="mb-3 text-sm font-semibold text-slate-900">
        Planning settings <span className="font-normal text-slate-500">— change any value and the whole page recalculates</span>
      </p>
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
      {FIELDS.map((f) => {
        const spec = specs.find((s) => s.key === f.key);
        return spec ? <Field key={f.key} label={f.label} spec={spec} value={plan[f.key]} onCommit={(v) => onChange(f.key, v)} /> : null;
      })}
      {changed && (
        <button type="button" onClick={onReset}
                className="mb-0.5 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-800 hover:bg-blue-100">
          Reset to default
        </button>
      )}
      {usageMonths !== null && <span className="pb-2 text-xs text-slate-500">Usage based on the last {usageMonths} months</span>}
      </div>
      {maxCover && (
        <p className="mt-3 text-xs text-slate-500">
          Note: Excess stock does not change with these settings. It is stock above {String(maxCover.default)} days of usage, a separate limit.
        </p>
      )}
    </div>
  );
}
