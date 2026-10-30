import { toQuery } from "./api";
import type { ItemDetail, PredictOptions, PredictOverview, StatusDetail } from "./predict-types";
import type { FilterState } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", signal });
  if (!res.ok) {
    // The backend explains what is wrong: show that, not a bare status.
    let detail = `API ${res.status}`;
    try { const j = await res.json(); if (j?.detail) detail = String(j.detail); } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// Top-bar Region / Zone / Cluster / Unit / Stock Take Group / Department apply.
// The Period does not: planning always looks forward from the latest stock snapshot.
function query(filters: FilterState, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams(toQuery(filters));
  Object.entries(extra).forEach(([k, v]) => q.set(k, v));
  return q.toString();
}

export const fetchPredictOptions = () => getJson<PredictOptions>("/api/predict/options");

export const fetchPredictOverview = (f: FilterState, signal?: AbortSignal) =>
  getJson<PredictOverview>(`/api/predict/overview?${query(f)}`, signal);

export const fetchPredictStatus = (f: FilterState, status: string, signal?: AbortSignal) =>
  getJson<StatusDetail>(`/api/predict/status?${query(f, { status })}`, signal);

export const fetchPredictItem = (f: FilterState, itemId: string, unitId: string, signal?: AbortSignal) =>
  getJson<ItemDetail>(`/api/predict/item?${query(f, { item_id: itemId, unit_id: unitId })}`, signal);
