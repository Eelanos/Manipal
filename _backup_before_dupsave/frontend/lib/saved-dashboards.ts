"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { ResultBlock } from "./chat-types";

// Dashboards created by Ask QBER and saved with "Save Dashboard". The whole
// result block is kept (a snapshot of what the user saw), in this browser's
// localStorage. If storage is blocked or full we fall back to memory for the
// session, so the button still works - it just won't survive a reload.
const KEY = "qber:saved-dashboards";
const EVENT = "qber:saved-dashboards-changed";
let memory = "[]";

export interface SavedDashboard {
  id: string;
  title: string;
  savedAt: number;
  block: ResultBlock;
}

/** Same question + same result = same dashboard, so saving twice cannot duplicate it. */
export function dashboardId(block: ResultBlock): string {
  const s = `${block.title}|${JSON.stringify(block.spec ?? {})}`;
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return `${block.title}:${(h >>> 0).toString(36)}`;
}

function read(): string {
  try {
    return window.localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

function parse(raw: string): SavedDashboard[] {
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((x) => x && typeof x.id === "string" && x.block) : [];
  } catch {
    return [];
  }
}

export function useSavedDashboards() {
  const raw = useSyncExternalStore(subscribe, read, () => "[]");
  const saved = useMemo(() => parse(raw), [raw]);

  /** Save the block, or remove it if it is already saved. */
  const toggle = useCallback((block: ResultBlock) => {
    const id = dashboardId(block);
    const current = parse(read());
    const next = current.some((d) => d.id === id)
      ? current.filter((d) => d.id !== id)
      : [...current, { id, title: block.title, savedAt: Date.now(), block }];
    memory = JSON.stringify(next);
    try {
      window.localStorage.setItem(KEY, memory);
    } catch {
      /* storage blocked or full - the memory copy keeps it working this session */
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);

  return { saved, toggle };
}
