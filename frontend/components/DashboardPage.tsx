"use client";

import { useEffect, useState } from "react";
import ChartPanel from "@/components/ChartPanel";
import InsightCallout from "@/components/InsightCallout";
import KpiCard from "@/components/KpiCard";
import NavIcon from "@/components/NavIcons";
import SaveToWorkspaceModal from "@/components/SaveToWorkspaceModal";
import { fetchDashboard } from "@/lib/api";
import { useFavorites } from "@/lib/favorites";
import { useFilters } from "@/lib/filter-context";
import type { DashboardResponse } from "@/lib/types";
import { dashKey, useWorkspaces } from "@/lib/workspaces";

interface Props {
  slug: string;
  title: string;
}

// Every dashboard renders through this one component. Filters are no longer
// owned here - they live once, in the sidebar (see layout.tsx +
// lib/filter-context.tsx), so switching pages never resets them.
export default function DashboardPage({ slug, title }: Props) {
  const { filters } = useFilters();
  const { favorites, toggle } = useFavorites();
  const isFavorite = favorites.includes(slug);
  const { assign, unassign } = useWorkspaces();
  const [picking, setPicking] = useState(false);   // "Save Dashboard to Workspace" dialog
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchDashboard(slug, filters)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [slug, filters]);

  return (
    <div className="space-y-5">
      <header className="flex items-center gap-2">
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        {/* Star: asks which workspace to save this dashboard to (click again to remove). */}
        <button type="button"
                onClick={() => {
                  if (isFavorite) { toggle(slug); unassign(dashKey(slug)); }
                  else setPicking(true);
                }}
                aria-pressed={isFavorite}
                aria-label={isFavorite ? "Remove from favorites" : "Save to favorites"}
                title={isFavorite ? "Remove from favorites" : "Save to favorites"}
                className={`rounded-md p-1.5 transition hover:bg-white ${
                  isFavorite ? "text-amber-500" : "text-slate-400 hover:text-amber-500"}`}>
          <NavIcon name="favorites" size={20} filled={isFavorite} />
        </button>
      </header>

      {picking && (
        <SaveToWorkspaceModal
          itemTitle={title}
          onClose={() => setPicking(false)}
          onSave={(wsId) => {
            if (!isFavorite) toggle(slug);
            assign(dashKey(slug), wsId);
            setPicking(false);
          }} />
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Could not reach the API. Is the backend running on port 8000?
        </div>
      )}

      {loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg bg-slate-200" />
            ))}
          </div>
          <div className="h-72 animate-pulse rounded-lg bg-slate-200" />
        </div>
      )}

      {!loading && data && data.row_count === 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-10 text-center">
          <p className="text-slate-600">No data for the selected filters.</p>
        </div>
      )}

      {!loading && data && data.row_count > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            {data.kpis.map((k) => <KpiCard key={k.label} kpi={k} />)}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {data.charts.map((c) => <ChartPanel key={c.id} spec={c} />)}
          </div>
        </>
      )}
    </div>
  );
}