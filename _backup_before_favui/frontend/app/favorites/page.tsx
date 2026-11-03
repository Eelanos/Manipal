"use client";

import Link from "next/link";
import { useState } from "react";
import { Block } from "@/components/chat/MessageView";
import NavIcon from "@/components/NavIcons";
import { useFavorites } from "@/lib/favorites";
import { DASHBOARDS } from "@/lib/nav";
import { useSavedDashboards } from "@/lib/saved-dashboards";
import { aiKey, dashKey, useWorkspaces } from "@/lib/workspaces";

export default function Page() {
  const { favorites, toggle } = useFavorites();
  const saved = DASHBOARDS.filter((d) => favorites.includes(d.slug));
  const { saved: aiSaved } = useSavedDashboards();
  const { workspaces, items, unassign, create } = useWorkspaces();
  const [adding, setAdding] = useState(false);       // "+ New Workspace" name box
  const [name, setName] = useState("");
  const addWorkspace = () => {
    if (create(name)) { setName(""); setAdding(false); }
  };

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

  return (
    <div className="space-y-5">
      <header className="space-y-3">
        <h1 className="flex items-center gap-3 text-3xl font-bold text-brand-dark">
          <span aria-hidden>&#11088;</span> My Dashboard
        </h1>
        <p className="text-sm text-slate-500">My AI-generated insights, organized in one place</p>
        <div className="flex flex-wrap items-center gap-2">
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

      {saved.length === 0 && aiSaved.length === 0 && workspaces.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-10 text-center">
          <p className="text-slate-600">
            No favorites yet. Click the star next to a dashboard title, or Save Dashboard
            under an Ask QBER answer, to keep it here.
          </p>
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.id || "unassigned"} aria-label={`${g.name} workspace`} className="space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {g.name}
              <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-medium normal-case tracking-normal text-slate-600">
                {g.dashboards.length + g.ai.length}
              </span>
            </h2>

            {g.dashboards.length + g.ai.length === 0 && (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-5 text-sm text-slate-500">
                Nothing saved here yet. Use the star on a dashboard, or Save Dashboard under an Ask QBER
                answer, and pick this workspace.
              </p>
            )}

            {g.dashboards.length > 0 && (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {g.dashboards.map((d) => (
                  <div key={d.slug}
                       className="flex items-center justify-between rounded-lg border border-slate-200
                                  bg-white p-5 transition hover:border-brand hover:shadow-sm">
                    <Link href={`/${d.slug}`}
                          className="text-sm font-medium text-slate-900 hover:text-brand">
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
              </div>
            )}

            {/* Dashboards created by Ask QBER and saved with "Save Dashboard". */}
            {g.ai.map((d) => (
              <div key={d.id} className="@container rounded-xl border border-slate-200 bg-white p-4">
                <Block block={d.block} savedId={d.id} />
              </div>
            ))}
          </section>
        ))
      )}
    </div>
  );
}
