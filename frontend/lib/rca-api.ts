import { toQuery } from "./api";
import type { FilterState } from "./types";
import type { RcaAnalysis, RcaOptions, RcaTree } from "./rca-types";

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

export const fetchRcaAnalysis = (p: Params, f: FilterState, path: string[], signal?: AbortSignal) =>
  getJson<RcaAnalysis>(`/api/rca/analysis?${query(p, f, path)}`, signal);

export const fetchRcaTree = (p: Params, f: FilterState, signal?: AbortSignal) =>
  getJson<RcaTree>(`/api/rca/tree?${query(p, f)}`, signal);
