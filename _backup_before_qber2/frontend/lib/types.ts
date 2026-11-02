// Mirrors app/schemas.py on the backend. If you change the envelope there,
// change it here - these two files are a contract.

export type Tone = "neutral" | "positive" | "risk";

export type ChartType =
  | "line" | "bar" | "hbar" | "stacked_bar"
  | "donut" | "area" | "grouped_bar" | "combo";

export interface Kpi {
  label: string;
  value: number;
  display: string;
  delta_pct: number | null;
  tone: Tone;
  note: string | null;
}

export interface ChartSeries {
  name: string;
  data: Record<string, string | number>[];
}

export interface Chart {
  id: string;
  title: string;
  type: ChartType;
  x_key: string;
  series: ChartSeries[];
  reference_line: number | null;
  value_format: "currency" | "percent" | "number";
  drilldown?: Record<string, { Department: string; Value: number }[] | { name: string; value: number }[] | { Unit: string; Stock: number; "Inventory Days": number }[]> | null;
}

export interface TableColumn {
  key: string;
  label: string;
  type: string;
}

export interface TableData {
  columns: TableColumn[];
  rows: Record<string, string | number>[];
}

export interface DashboardResponse {
  filters: Record<string, string>;
  kpis: Kpi[];
  charts: Chart[];
  table: TableData;
  insights: string[];
  row_count: number;
}

// Each unit carries its full ancestry, so the FilterBar can cascade the
// dropdowns without another round trip to the API.
export interface UnitOption {
  Unit_ID: string;
  Unit_Name: string;
  Cluster: string;
  Zone: string;
  Region: string;
}

export interface FilterOptions {
  regions: string[];
  zones: string[];
  clusters: string[];
  units: UnitOption[];
  departments: string[];
  stock_take_groups: string[];
  presets: string[];
  tier_labels: Record<string, string>;
  date_min: string;
  date_max: string;
}

export interface FilterState {
  region: string;
  zone: string;
  cluster: string;
  unit: string;
  department: string;
  stock_take_group: string;
  preset: string;
}
