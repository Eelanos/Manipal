"use client";

import { useEffect, useRef } from "react";

// Modals can stack (status list -> item). Esc closes only the top one.
const openModals: symbol[] = [];

// Same look as DrilldownModal (slate header, brand close button) but wider and
// with Esc / click-outside to close, because these hold tables and charts.
export default function Modal({ title, subtitle, onClose, wide = false, children }: {
  title: string; subtitle?: string; onClose: () => void; wide?: boolean; children: React.ReactNode;
}) {
  // onClose changes identity on every parent render; keep the latest in a ref so the
  // listener registers once per modal (its place in the stack = the order it opened).
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  useEffect(() => {
    const id = Symbol("modal");
    openModals.push(id);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && openModals[openModals.length - 1] === id) closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      openModals.splice(openModals.indexOf(id), 1);
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
           className={`flex max-h-[90vh] w-full flex-col rounded-lg bg-white shadow-xl ${wide ? "max-w-4xl" : "max-w-2xl"}`}>
        <div className="flex items-start justify-between rounded-t-lg bg-nav px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold text-white">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-slate-300">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-white/80 hover:text-white">✕</button>
        </div>
        <div className="overflow-y-auto p-5">{children}</div>
        <div className="flex justify-end border-t border-slate-100 px-5 py-3">
          <button type="button" onClick={onClose} className="rounded bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand-dark">Close</button>
        </div>
      </div>
    </div>
  );
}
