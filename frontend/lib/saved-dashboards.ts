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

/** Every save is its own saved dashboard (the demo lets the same answer be saved as often as wanted),
 *  so each save gets a fresh id: the content hash plus a unique suffix. */
export function dashboardId(block: ResultBlock): string {
  const s = `${block.title}|${JSON.stringify(block.spec ?? {})}`;
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  const unique = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  return `${block.title}:${(h >>> 0).toString(36)}:${unique}`;
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

  const write = (next: SavedDashboard[]) => {
    memory = JSON.stringify(next);
    try {
      window.localStorage.setItem(KEY, memory);
    } catch {
      /* storage blocked or full - the memory copy keeps it working this session */
    }
    window.dispatchEvent(new Event(EVENT));
  };

  /** Save the block as a new saved dashboard (always a new one) and return its id. */
  const add = useCallback((block: ResultBlock): string => {
    const id = dashboardId(block);
    write([...parse(read()), { id, title: block.title, savedAt: Date.now(), block }]);
    return id;
  }, []);

  /** Remove one saved dashboard by id. */
  const remove = useCallback((id: string) => {
    write(parse(read()).filter((d) => d.id !== id));
  }, []);

  return { saved, add, remove };
}
