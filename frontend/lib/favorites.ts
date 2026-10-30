"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

// Favourite dashboards are kept in this browser (localStorage) as a list of
// slugs. If storage is blocked we fall back to memory for the session, so the
// star still works - it just won't survive a reload.
const KEY = "qber:favorites";
const EVENT = "qber:favorites-changed";
let memory = "[]";

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

function parse(raw: string): string[] {
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function useFavorites() {
  const raw = useSyncExternalStore(subscribe, read, () => "[]");
  const favorites = useMemo(() => parse(raw), [raw]);

  const toggle = useCallback((slug: string) => {
    const current = parse(read());
    const next = current.includes(slug)
      ? current.filter((s) => s !== slug)
      : [...current, slug];
    memory = JSON.stringify(next);
    try {
      window.localStorage.setItem(KEY, memory);
    } catch {
      /* storage blocked - memory copy keeps the star working this session */
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);

  return { favorites, toggle };
}
