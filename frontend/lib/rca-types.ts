// Mirrors the JSON from app/routers/rca.py (app/rca/engine.py and app/rca/tree.py).
// These are a contract with the backend: change one, change the other.

export type RcaFmt = "currency" | "percent" | "days";
export type HigherIs = "better" | "worse" | "neutral";
export type EvidenceFlag = "unusual" | "watch" | "normal";

export interface RcaOptions {
  metrics: {
    key: string; label: string; fmt: RcaFmt; unit_word: string; higher_is: HigherIs; definition: string;
    compares: { key: string; label: string }[];
    dims: { key: string; label: string }[];
    has_tree: boolean; tree_compares: string[];
  }[];
  months: { value: string; label: string; has_prior_month: boolean; has_same_month_last_year: boolean }[];
  default_month: string;
  home_cards?: number;
  // The rules behind every status badge (from the backend config, never typed in here).
  thresholds?: { z_unusual: number; z_watch: number; material_share_pct: number; min_overindex_pp: number; min_history_months: number };
}

export interface RcaEvidence {
  available: boolean;
  reason?: string;
  basis: string;
  value?: number; z?: number; n?: number; mean?: number; sd?: number;
  flag?: EvidenceFlag;
  history?: { month: string; value: number | null }[];
  focus_month?: string;
  same_month_last_year?: { month: string; value: number | null };
}

export type EntityFlag = "deviating" | "watch" | "normal" | "minor" | "no_history";
export type RowTone = "good" | "bad" | "neutral";

export interface RcaRow {
  segment: string;
  // Added with the command-center views (older responses may not carry them).
  share_of_slice_pct?: number | null;
  weight_in_slice_pct?: number | null;
  flag?: EntityFlag;
  tone?: RowTone;
  contribution: number | null;
  share_pct: number | null;
  own_current: number | null;
  own_base: number | null;
  weight_pct: number | null;
  parts?: Record<string, number | null>;
  evidence: RcaEvidence;
}

export interface RcaDimension {
  key: string; label: string; segments: number;
  rows: RcaRow[];
  other: { label: string; count: number; contribution: number | null; share_pct: number | null } | null;
  top_segment: string | null;
  top1_share_pct: number | null; top3_share_pct: number | null;
  pattern: "Concentrated" | "Moderate" | "Spread out" | null;
  offsets: boolean;   // one segment moved more than the whole net change; others moved the other way
  total: number | null;
  slice_total?: number | null;
  slice_flat?: boolean;
  gross?: number | null;
}

export interface RcaAnalysis {
  metric: { key: string; label: string; fmt: RcaFmt; unit_word: string; higher_is: HigherIs; definition: string; weight_label: string };
  period: { month: string; label: string };
  compare: { key: string; label: string; base_month: string | null };
  scope: { filters: Record<string, string>; path: { dim: string; dim_label: string; value: string }[] };
  headline: { current: number; base: number; delta: number; delta_pct: number | null; tone: "good" | "bad" | "neutral"; flat: boolean };
  effects: { label: string; contribution: number | null }[];
  dimensions: RcaDimension[];
  unavailable_dimensions: { key: string; label: string; reason: string }[];
  chain: { label: string; dim: string | null; segment: string | null; contribution: number | null; share_pct: number | null }[];
  slice_total?: number | null;
  suggestion: { dim: string; dim_label: string; segment: string; share_pct: number; pattern: string | null } | null;
  evidence: RcaEvidence;
  reconciliation: { ok: boolean; max_gap: number | null; checked: string };
  narrative: string[];
}

export type TreeFlag = "deviating" | "watch" | "normal" | "minor" | "no_history";

export interface TreeSplitRow {
  segment: string; impact: number | null; share_pct: number | null;
  current: number | null; base: number | null; change: number | null;
  evidence: RcaEvidence; flag: TreeFlag;
}
export interface TreeSplit {
  key: string; label: string; segments: number; rows: TreeSplitRow[];
  other: { label: string; impact: number | null } | null;
  top_segment: string | null; top1_share_pct: number | null; pattern: string | null;
}
export interface TreeNode {
  id: string; label: string; how: string;
  kind: "kpi" | "quantity" | "effect";
  fmt: RcaFmt | null;
  current: number | null; base: number | null; change: number | null;
  impact: number | null; share_pct: number | null;
  evidence: RcaEvidence; flag: TreeFlag;
  splits: TreeSplit[]; children: TreeNode[];
}
export interface RcaTree {
  metric: RcaAnalysis["metric"];
  period: { month: string; label: string };
  compare: { key: string; label: string };
  scope?: { filters: Record<string, string>; path: { dim: string; dim_label: string; value: string }[] };
  tree: TreeNode;
  chain: { id: string; label: string; impact: number | null; share_pct: number | null; flag: TreeFlag }[];
  flat: boolean;
  reconciliation: { ok: boolean; max_gap: number | null; checked: string };
  thresholds: { material_share_pct: number };
  narrative: string[];
}

// ---- Command-center views: /api/rca/lens, /cause, /entity ------------------------------------

export interface TopCause {
  dim: string; dim_label: string; segment: string;
  share_of_slice_pct: number; weight_in_slice_pct: number | null; tone: RowTone;
}

export interface LensEntity extends RcaRow {
  flag: EntityFlag; tone: RowTone;
  own_change: number | null;
  top_cause: TopCause | null;
}

export interface LensInfo { key: string; label: string; segments: number }

export interface RcaLens {
  metric: RcaAnalysis["metric"];
  period: { month: string; label: string };
  compare: { key: string; label: string; base_month: string | null };
  scope: { filters: Record<string, string> };
  headline: RcaAnalysis["headline"];
  evidence: RcaEvidence;
  effects: { label: string; contribution: number | null }[];
  lens: LensInfo;
  lenses: LensInfo[];
  entities: LensEntity[];
  summary: {
    count: number;
    flags: Record<EntityFlag, number>;
    top1_share_pct: number | null; top3_share_pct: number | null;
    pattern: "Concentrated" | "Moderate" | "Spread out" | null;
    offsets: boolean; gross: number | null;
    biggest_up: { segment: string; contribution: number } | null;
    biggest_down: { segment: string; contribution: number } | null;
  };
  reconciliation: { ok: boolean; max_gap: number | null; checked: string };
  narrative: string[];
}

export interface RankedDriver {
  dim: string; dim_label: string; segment: string;
  contribution: number | null;
  share_of_slice_pct: number; weight_in_slice_pct: number | null;
  own_current: number | null; own_base: number | null;
  flag: EntityFlag; tone: RowTone; evidence: RcaEvidence;
}

export interface RcaEntityView {
  metric: RcaAnalysis["metric"];
  period: { month: string; label: string };
  compare: { key: string; label: string; base_month: string | null };
  scope: RcaAnalysis["scope"];
  headline: RcaAnalysis["headline"];
  entity: LensEntity & { dim: string; dim_label: string };
  ranking: RankedDriver[];
  slice_total: number | null;
  peer_summary: { count: number; flags: Record<EntityFlag, number> };
  reconciliation: { ok: boolean; max_gap: number | null; checked: string };
  narrative: string[];
}
