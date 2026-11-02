"use client";

import Link from "next/link";
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
  const { workspaces, items, unassign } = useWorkspaces();

  // Favourites are grouped by the workspace they were saved to. Anything saved
  // before workspaces existed (no workspace) goes under "Unassigned".
  const groups = [
    ...workspaces.map((w) => ({ id: w.id, name: w.name })),
    { id: "", name: "Unassigned" },
  ].map((g) => ({
    ...g,
    dashboards: saved.filter((d) => (items[dashKey(d.slug)] ?? "") === g.id),
    ai: aiSaved.filter((d) => (items[aiKey(d.id)] ?? "") === g.id),
  })).filter((g) => g.dashboards.length + g.ai.length > 0);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">Favorites</h1>
      </header>

      {saved.length === 0 && aiSaved.length === 0 ? (
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
                <Block block={d.block} />
              </div>
            ))}
          </section>
        ))
      )}
    </div>
  );
}
