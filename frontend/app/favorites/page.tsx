"use client";

import Link from "next/link";
import { Block } from "@/components/chat/MessageView";
import NavIcon from "@/components/NavIcons";
import { useFavorites } from "@/lib/favorites";
import { DASHBOARDS } from "@/lib/nav";
import { useSavedDashboards } from "@/lib/saved-dashboards";

export default function Page() {
  const { favorites, toggle } = useFavorites();
  const saved = DASHBOARDS.filter((d) => favorites.includes(d.slug));
  const { saved: aiSaved } = useSavedDashboards();

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
      ) : saved.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {saved.map((d) => (
            <div key={d.slug}
                 className="flex items-center justify-between rounded-lg border border-slate-200
                            bg-white p-5 transition hover:border-brand hover:shadow-sm">
              <Link href={`/${d.slug}`}
                    className="text-sm font-medium text-slate-900 hover:text-brand">
                {d.title}
              </Link>
              <button type="button" onClick={() => toggle(d.slug)}
                      aria-label={`Remove ${d.title} from favorites`}
                      title="Remove from favorites"
                      className="rounded-md p-1.5 text-amber-500 hover:bg-slate-100">
                <NavIcon name="favorites" filled />
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {/* Dashboards created by Ask QBER and saved with "Save Dashboard". */}
      {aiSaved.map((d) => (
        <div key={d.id} className="@container rounded-xl border border-slate-200 bg-white p-4">
          <Block block={d.block} />
        </div>
      ))}
    </div>
  );
}
