import { toQuery } from "./api";
import type { FilterState } from "./types";
import type { RcaAnalysis, RcaEntityView, RcaLens, RcaOptions, RcaTree, TopCause } from "./rca-types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", signal });
  if (!res.ok) {
    // The backend explains what is wrong ("There is no data for ..."): show that, not a bare status.
    let detail = `API ${res.status}`;
    try { const j = await res.json(); if (j?.detail) detail = String(j.detail); } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const fetchRcaOptions = () => getJson<RcaOptions>("/api/rca/options");

interface Params { metric: string; month: string; compare: string }

// The top-bar Unit / Stock Take Group / Department apply. The Period does not:
// RCA explains one month, chosen on the RCA page.
function query(p: Params, filters: FilterState, path: string[] = []): string {
  const q = new URLSearchParams(toQuery(filters));
  q.set("metric", p.metric); q.set("month", p.month); q.set("compare", p.compare);
  path.forEach((s) => q.append("path", s));
  return q.toString();
}

export const fetchRcaAnalysis = (p: Params, f: FilterState, path: string[], signal?: AbortSignal, full = false) =>
  getJson<RcaAnalysis>(`/api/rca/analysis?${query(p, f, path)}${full ? "&full=true" : ""}`, signal);

export const fetchRcaTree = (p: Params, f: FilterState, signal?: AbortSignal, path: string[] = []) =>
  getJson<RcaTree>(`/api/rca/tree?${query(p, f, path)}`, signal);

// ---- command-center views --------------------------------------------------
const withView = (p: Params, f: FilterState, extra: Record<string, string>) => {
  const q = new URLSearchParams(query(p, f));
  Object.entries(extra).forEach(([k, v]) => q.set(k, v));
  return q.toString();
};

/** Every entity of one kind (all units, all doctors ...) with its part of the change. */
export const fetchRcaLens = (p: Params, f: FilterState, dim: string, signal?: AbortSignal) =>
  getJson<RcaLens>(`/api/rca/lens?${withView(p, f, { dim })}`, signal);

/** The strongest driver inside one entity. Fetched per card so the cards can appear first. */
export const fetchRcaCause = (p: Params, f: FilterState, dim: string, segment: string, signal?: AbortSignal) =>
  getJson<{ segment: string; dim: string; top_cause: TopCause | null }>(`/api/rca/cause?${withView(p, f, { dim, segment })}`, signal);

export const fetchRcaEntity = (p: Params, f: FilterState, dim: string, segment: string, signal?: AbortSignal) =>
  getJson<RcaEntityView>(`/api/rca/entity?${withView(p, f, { dim, segment })}`, signal);
