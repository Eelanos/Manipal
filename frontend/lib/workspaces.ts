"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

// Workspaces group the dashboards a user favourites (Sales, Finance, Ops ...).
// The user creates them in the "Save Dashboard to Workspace" dialog; nothing is
// pre-made. Kept in this browser (localStorage) next to the favourites, with a
// memory fallback if storage is blocked, like lib/favorites.ts.
//
// items maps a saved dashboard to its workspace:
//   "dash:<slug>"  - a built-in dashboard saved with the star
//   "ai:<id>"      - a dashboard created by Ask QBER (see saved-dashboards.ts)
const KEY = "qber:workspaces";
const EVENT = "qber:workspaces-changed";
let memory = JSON.stringify({ list: [], items: {} });

export interface Workspace {
  id: string;
  name: string;
}

interface State {
  list: Workspace[];
  items: Record<string, string>;
}

export const dashKey = (slug: string) => `dash:${slug}`;
export const aiKey = (id: string) => `ai:${id}`;

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

function parse(raw: string): State {
  try {
    const v = JSON.parse(raw);
    const list = Array.isArray(v?.list)
      ? v.list.filter((w: unknown): w is Workspace =>
          !!w && typeof (w as Workspace).id === "string" && typeof (w as Workspace).name === "string")
      : [];
    const items: Record<string, string> = {};
    if (v?.items && typeof v.items === "object") {
      for (const [k, id] of Object.entries(v.items)) {
        if (typeof id === "string" && list.some((w: Workspace) => w.id === id)) items[k] = id;
      }
    }
    return { list, items };
  } catch {
    return { list: [], items: {} };
  }
}

function write(next: State) {
  memory = JSON.stringify(next);
  try {
    window.localStorage.setItem(KEY, memory);
  } catch {
    /* storage blocked - the memory copy keeps it working this session */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useWorkspaces() {
  const raw = useSyncExternalStore(subscribe, read, () => memory);
  const state = useMemo(() => parse(raw), [raw]);

  /** Create a workspace (or return the existing one with the same name). */
  const create = useCallback((name: string): Workspace | null => {
    const clean = name.trim().replace(/\s+/g, " ").slice(0, 40);
    if (!clean) return null;
    const cur = parse(read());
    const existing = cur.list.find((w) => w.name.toLowerCase() === clean.toLowerCase());
    if (existing) return existing;
    const ws = { id: `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`, name: clean };
    write({ ...cur, list: [...cur.list, ws] });
    return ws;
  }, []);

  const assign = useCallback((key: string, workspaceId: string) => {
    const cur = parse(read());
    write({ ...cur, items: { ...cur.items, [key]: workspaceId } });
  }, []);

  const unassign = useCallback((key: string) => {
    const cur = parse(read());
    const { [key]: _drop, ...rest } = cur.items;
    void _drop;
    write({ ...cur, items: rest });
  }, []);

  return { workspaces: state.list, items: state.items, create, assign, unassign };
}
