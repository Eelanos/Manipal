import type { Kpi } from "./types";

// Mirrors GET /api/predict/*. Nothing here is a business rule: defaults, limits,
// statuses and horizons all arrive from /api/predict/options.

export type Settings = Record<string, number | boolean>;

export interface PredictOptions {
  as_of: string;
  horizon_days: number;
}

export interface ForecastPoint {
  month: string;
  label: string;
  actual: number | null;
  forecast: number | null;
  low: number | null;
  high: number | null;
}

export interface Forecast {
  points: ForecastPoint[];
  accuracy_pct: number | null;
  range_available: boolean;
  season_used: boolean;
  has_forecast: boolean;
  forecast_total?: number;
}

export interface LineRow {
  item_id: string;
  item_name: string;
  unit_id: string;
  unit_name: string;
  group: string;
  status: string;
  on_hand: number;
  on_order: number;
  daily_usage: number;
  cover_days: number | null;
  cover_capped: boolean;
  reorder_point: number;
  order_qty: number;
  order_value: number;
  order_in_days: number | null;
  excess_qty: number;
  excess_value: number;
  stock_value: number;
}

export interface CoverRow {
  label: string;
  item_id: string;
  unit_id: string;
  cover_days: number;
  capped: boolean;
  status: string;
  on_order: number;
}

export interface HealthSlice {
  status: string;
  lines: number;
  stock_value: number;
  help: string;
  rule: string;
}

export interface StatusDetail extends RowsBlock {
  status: string;
  help: string;
  rule: string;
  stock_value: number;
  order_value: number;
  excess_value: number;
}

export interface RowsBlock {
  rows: LineRow[];
  more: boolean;
  total: number;
}

export interface PredictOverview {
  as_of: string;
  scope: string;
  filters: Record<string, string>;
  settings: Settings;
  empty: boolean;
  department_note: boolean;
  kpis: Kpi[];
  forecast: Forecast;
  cover: { rows: CoverRow[]; lead_days: number };
  health: HealthSlice[];
  reorder: RowsBlock;
  excess: RowsBlock;
  insights: string[];
  notes: string[];
  row_count: number;
}

export interface ItemFacts {
  expired_qty: number;
  on_hand: number;
  on_order: number;
  position: number;
  daily_usage: number;
  cover_days: number | null;
  cover_capped: boolean;
  reorder_point: number;
  order_up_to: number;
  order_qty: number;
  order_value: number;
  unit_price: number;
  order_in_days: number | null;
  order_by: string | null;
  excess_qty: number;
  excess_value: number;
}

export interface ItemDetail {
  item_id: string;
  item_name: string;
  unit_id: string;
  unit_name: string;
  group: string;
  status: string;
  status_help: string;
  as_of: string;
  settings: Settings;
  facts: ItemFacts;
  history: { label: string; actual: number | null; forecast: number | null }[];
  projection: { day: number; date: string; stock: number; reorder_point: number }[];
  batches: {
    batch: string;
    expiry: string | null;
    days_to_expiry: number;
    qty: number;
    expected_used: number;
    at_risk_qty: number;
    at_risk_value: number;
    state: string;
  }[];
  explain: string[];
  notes: string[];
}
