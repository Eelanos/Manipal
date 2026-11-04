"use client";

import { useState } from "react";
import Modal from "./Modal";
import { h2 } from "./shared";

// A compact card that opens the full "How the numbers are worked out" explanation in a pop-up.
// Content is exactly what used to sit in the page; `notes` are the backend's snapshot / assumption notes.
export default function NumbersHelp({ notes }: { notes: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog"
              className="flex h-full w-full items-center gap-2.5 rounded-lg border border-slate-200 bg-white px-5 py-4 text-left shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600" aria-hidden>
          <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
        </span>
        <span className="flex-1">
          <span className={`${h2} block`}>How the numbers are worked out</span>
          <span className="mt-0.5 block text-xs text-slate-500">Click to see the formulas and assumptions</span>
        </span>
        <span className="text-lg text-slate-400" aria-hidden>›</span>
      </button>
      {open && (
        <Modal title="How the numbers are worked out" onClose={() => setOpen(false)}>
          <ul className="space-y-1.5 text-sm text-slate-700">
            <li><b>Daily usage</b> = quantity used in the period ÷ days in it.</li>
            <li><b>Days of cover</b> = how many days current stock lasts at that usage.</li>
            <li><b>Reorder point</b> = usage over the delivery time + safety buffer.</li>
            <li><b>Order quantity</b> = usage over delivery + buffer + order-cover days, minus stock and open orders.</li>
            <li><b>Excess</b> = stock above the maximum days of usage.</li>
            <li><b>Seasonality</b> = busy months (for example December) are scaled up and quiet ones down, using the same month in earlier years.</li>
          </ul>
          <ul className="mt-3 space-y-0.5 border-t border-slate-100 pt-2 text-[11px] leading-snug text-slate-500">
            {notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </Modal>
      )}
    </>
  );
}
