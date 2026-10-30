// Mirrors backend/app/chat (present.py ResultBlock, narrative.py NarrativeOut and
// the SSE events in router.py). If the backend envelope changes, change it here.

import type { Chart, Kpi } from "./types";

export interface ChatColumn {
  key: string;
  label: string;
  /** text | currency | number | percent | decimal */
  type: string;
}

export type ChatCell = string | number | null;

export interface ChatTableData {
  columns: ChatColumn[];
  rows: Record<string, ChatCell>[];
  totals: Record<string, ChatCell> | null;
  truncated: boolean;
}

export interface ResultBlock {
  id: string;
  title: string;
  scope: string[];
  notes: string[];
  kpis: Kpi[];
  charts: Chart[];
  table: ChatTableData | null;
  /** A chart already shows this data, so the table sits behind a toggle. */
  table_collapsed: boolean;
  empty: boolean;
  message: string | null;
  /** The executed query, echoed back to the server as conversation memory. */
  spec: Record<string, unknown>;
}

export interface Narrative {
  headline: string;
  insights: string[];
  recommendations: string[];
  follow_ups: string[];
  source: "llm" | "fallback";
}

export type NoticeKind =
  | "clarify" | "out_of_scope" | "chat" | "not_found" | "failed" | "error";

export interface UserMessage {
  id: number;
  role: "user";
  text: string;
}

export interface AssistantMessage {
  id: number;
  role: "assistant";
  question: string;
  status: "working" | "done";
  stage: string;
  blocks: ResultBlock[];
  narrative: Narrative | null;
  notice: { kind: NoticeKind; text: string } | null;
}

export type ChatMessage = UserMessage | AssistantMessage;

/** What the server remembers about earlier turns. */
export interface HistoryTurn {
  question: string;
  specs: Record<string, unknown>[];
  answer: string;
}

export interface Suggestions {
  suggestions: string[];
  data?: { from: string; to: string; as_of: string };
}

export type ChatEvent =
  | { event: "status"; data: { stage: string; text: string } }
  | { event: "result"; data: { block: ResultBlock } }
  | { event: "narrative"; data: Narrative }
  | { event: "message"; data: { kind: NoticeKind; text: string } }
  | { event: "error"; data: { kind: string; text: string } }
  | { event: "done"; data: { ms?: Record<string, number>; cached?: boolean } };
