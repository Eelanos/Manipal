"use client";

import { useEffect, useRef, useState } from "react";
import { useWorkspaces } from "@/lib/workspaces";

// "Save Dashboard to Workspace": pick a workspace for the dashboard being
// favourited. There are no ready-made workspaces - the first time, only
// "+ New Workspace" shows; once some exist the user picks one (or adds another).
export default function SaveToWorkspaceModal({ itemTitle, onSave, onClose }: {
  itemTitle: string;
  onSave: (workspaceId: string) => void;
  onClose: () => void;
}) {
  const { workspaces, create } = useWorkspaces();
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (adding) inputRef.current?.focus(); }, [adding]);

  const addWorkspace = () => {
    const ws = create(name);
    if (!ws) return;
    setSelected(ws.id);
    setName("");
    setAdding(false);
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Save Dashboard to Workspace"
           className="w-full max-w-md rounded-lg bg-white shadow-xl">
        <div className="flex items-start justify-between rounded-t-lg bg-nav px-5 py-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-white">Save Dashboard to Workspace</h3>
            <p className="mt-0.5 truncate text-xs text-slate-300">{itemTitle}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
                  className="text-white/80 hover:text-white">&#10005;</button>
        </div>

        <div className="space-y-3 p-5">
          {workspaces.length > 0 && (
            <div role="radiogroup" aria-label="Workspaces" className="max-h-60 space-y-1.5 overflow-y-auto">
              {workspaces.map((w) => {
                const on = selected === w.id;
                return (
                  <button key={w.id} type="button" role="radio" aria-checked={on}
                          onClick={() => setSelected(w.id)}
                          className={`flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left text-sm transition ${
                            on ? "border-brand bg-red-50 text-slate-900"
                               : "border-slate-200 text-slate-700 hover:border-slate-300 hover:bg-slate-50"}`}>
                    <span aria-hidden
                          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                            on ? "border-brand" : "border-slate-300"}`}>
                      {on && <span className="h-2 w-2 rounded-full bg-brand" />}
                    </span>
                    {w.name}
                  </button>
                );
              })}
            </div>
          )}

          {adding ? (
            <div className="flex gap-2">
              <input ref={inputRef} value={name} maxLength={40}
                     onChange={(e) => setName(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") addWorkspace(); }}
                     placeholder="Workspace name (e.g. Sales)"
                     aria-label="New workspace name"
                     className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand" />
              <button type="button" onClick={addWorkspace} disabled={!name.trim()}
                      className="rounded-md bg-nav px-3 py-2 text-sm text-white disabled:opacity-40">
                Add
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => setAdding(true)}
                    className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-slate-300 px-3 py-2.5 text-sm font-medium text-brand hover:border-brand hover:bg-red-50">
              + New Workspace
            </button>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">
          <button type="button" onClick={onClose}
                  className="rounded border border-slate-300 px-4 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
            Cancel
          </button>
          <button type="button" disabled={!selected} onClick={() => selected && onSave(selected)}
                  className="rounded bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-40">
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
