"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Block } from "@/components/chat/MessageView";
import NavIcon from "@/components/NavIcons";
import { useFavorites } from "@/lib/favorites";
import { DASHBOARDS } from "@/lib/nav";
import { useSavedDashboards } from "@/lib/saved-dashboards";
import { aiKey, dashKey, useWorkspaces } from "@/lib/workspaces";

const count = (n: number) => `${n} Dashboard${n === 1 ? "" : "s"}`;

export default function Page() {
  const { favorites, toggle } = useFavorites();
  const saved = DASHBOARDS.filter((d) => favorites.includes(d.slug));
  const { saved: aiSaved, remove: removeAi } = useSavedDashboards();
  const { workspaces, items, unassign, create, removeWorkspace } = useWorkspaces();
  const [adding, setAdding] = useState(false);       // "+ New Workspace" name box
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string | null>(null);   // the workspace whose dashboards are shown
  const [deleting, setDeleting] = useState<string | null>(null); // workspace awaiting delete confirmation

  // Favourites are grouped by the workspace they were saved to. Anything saved
  // before workspaces existed (no workspace) goes under "Unassigned".
  const groups = [
    ...workspaces.map((w) => ({ id: w.id, name: w.name })),
    { id: "", name: "Unassigned" },
  ].map((g) => ({
    ...g,
    dashboards: saved.filter((d) => (items[dashKey(d.slug)] ?? "") === g.id),
    ai: aiSaved.filter((d) => (items[aiKey(d.id)] ?? "") === g.id),
  // A workspace stays visible while empty (it was just created); "Unassigned" only when it has items.
  })).filter((g) => g.id !== "" || g.dashboards.length + g.ai.length > 0);

  // The selected workspace; falls back to the first one if nothing (or a deleted one) is selected.
  const current = groups.find((g) => g.id === picked) ?? groups[0];
  const toDelete = groups.find((g) => g.id === deleting);

  const addWorkspace = () => {
    const ws = create(name);
    if (ws) { setName(""); setAdding(false); setPicked(ws.id); }
  };

  // Delete a workspace together with the dashboards saved in it.
  const confirmDelete = () => {
    if (!toDelete) return;
    toDelete.dashboards.forEach((d) => { toggle(d.slug); unassign(dashKey(d.slug)); });
    toDelete.ai.forEach((d) => { removeAi(d.id); unassign(aiKey(d.id)); });
    removeWorkspace(toDelete.id);
    setDeleting(null);
    if (picked === toDelete.id) setPicked(null);
  };

  // Esc closes the delete confirmation.
  useEffect(() => {
    if (!deleting) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDeleting(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleting]);

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <h1 className="flex items-center gap-3 text-4xl font-bold text-brand-dark">
          <span aria-hidden>&#11088;</span> My Dashboard
        </h1>
        <p className="text-base text-slate-500">My AI-generated insights, organized in one place</p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {adding ? (
            <>
              <input autoFocus value={name} maxLength={40} onChange={(e) => setName(e.target.value)}
                     onKeyDown={(e) => {
                       if (e.key === "Enter") addWorkspace();
                       if (e.key === "Escape") { setAdding(false); setName(""); }
                     }}
                     placeholder="Workspace name (e.g. Sales)" aria-label="New workspace name"
                     className="w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand" />
              <button type="button" onClick={addWorkspace} disabled={!name.trim()}
                      className="rounded-lg bg-brand-dark px-4 py-2 text-sm font-semibold text-white hover:bg-brand disabled:opacity-40">
                Add
              </button>
              <button type="button" onClick={() => { setAdding(false); setName(""); }}
                      className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">
                Cancel
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setAdding(true)}
                    className="rounded-xl bg-brand-dark px-5 py-3 text-sm font-bold text-white shadow-sm hover:bg-brand">
              + New Workspace
            </button>
          )}
        </div>
      </header>

      {groups.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-10 text-center">
          <p className="text-slate-600">
            No favorites yet. Click the star next to a dashboard title, or Save Dashboard
            under an Ask QBER answer, to keep it here.
          </p>
        </div>
      ) : (
        <>
          {/* One card per workspace; click one to see the dashboards saved in it. */}
          <div role="tablist" aria-label="Workspaces" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {groups.map((g) => {
              const n = g.dashboards.length + g.ai.length;
              const on = current?.id === g.id;
              return (
                <div key={g.id || "unassigned"} role="tab" tabIndex={0} aria-selected={on}
                     aria-label={`${g.name} workspace`}
                     onClick={() => setPicked(g.id)}
                     onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked(g.id); } }}
                     className={`cursor-pointer rounded-2xl border-2 p-5 shadow-sm transition ${
                       on ? "border-brand bg-red-50/60" : "border-transparent bg-white hover:border-slate-200 hover:shadow-md"}`}>
                  <h2 className="flex items-center gap-2 text-xl font-bold text-slate-900">
                    <span aria-hidden className="text-2xl">&#128193;</span>
                    <span className="truncate">{g.name}</span>
                  </h2>
                  <p className="mt-3 text-sm text-slate-500">Dashboard Workspace</p>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className="text-sm text-slate-800">{count(n)}</span>
                    {g.id !== "" && (
                      <button type="button" onClick={(e) => { e.stopPropagation(); setDeleting(g.id); }}
                              aria-label={`Delete ${g.name} workspace`}
                              className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* The selected workspace's dashboards, two to a row. */}
          {current && (
            current.dashboards.length + current.ai.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-5 text-sm text-slate-500">
                Nothing saved in {current.name} yet. Use the star on a dashboard, or Save Dashboard under an
                Ask QBER answer, and pick this workspace.
              </p>
            ) : (
              <div className="grid items-start gap-5 lg:grid-cols-2" aria-label={`${current.name} dashboards`}>
                {current.dashboards.map((d) => (
                  <div key={d.slug}
                       className="flex items-center justify-between rounded-2xl border border-slate-200
                                  bg-white p-6 shadow-sm transition hover:border-brand hover:shadow-md">
                    <Link href={`/${d.slug}`}
                          className="text-lg font-semibold text-slate-900 hover:text-brand">
                      {d.title}
                    </Link>
                    <button type="button"
                            onClick={() => { toggle(d.slug); unassign(dashKey(d.slug)); }}
                            aria-label={`Remove ${d.title} from favorites`}
                            title="Remove from favorites"
                            className="rounded-md p-1.5 text-amber-500 hover:bg-slate-100">
                      <NavIcon name="favorites" filled />
                    </button>
                  </div>
                ))}
                {/* Dashboards created by Ask QBER and saved with "Save Dashboard". */}
                {current.ai.map((d) => (
                  <div key={d.id} className="@container rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                    <Block block={d.block} savedId={d.id} />
                  </div>
                ))}
              </div>
            )
          )}
        </>
      )}

      {toDelete && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
             onMouseDown={(e) => { if (e.target === e.currentTarget) setDeleting(null); }}>
          <div role="dialog" aria-modal="true" aria-label="Delete workspace"
               className="w-full max-w-sm rounded-lg bg-white shadow-xl">
            <div className="rounded-t-lg bg-nav px-5 py-3">
              <h3 className="text-sm font-semibold text-white">Delete workspace</h3>
            </div>
            <p className="px-5 py-4 text-sm text-slate-700">
              Delete <strong>{toDelete.name}</strong>
              {toDelete.dashboards.length + toDelete.ai.length > 0
                ? ` and the ${count(toDelete.dashboards.length + toDelete.ai.length).toLowerCase()} saved in it?`
                : "?"}
              {" "}This can&apos;t be undone.
            </p>
            <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">
              <button type="button" onClick={() => setDeleting(null)}
                      className="rounded border border-slate-300 px-4 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
                Cancel
              </button>
              <button type="button" onClick={confirmDelete}
                      className="rounded bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand-dark">
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
