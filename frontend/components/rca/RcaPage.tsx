"use client";

// The RCA tab as a button-driven flow instead of one long page:
//
//   Command Center  -> pick a metric, month, comparison and a "view by" (region, unit, doctor ...);
//                      every entity of that kind shows as a card with its status and top driver
//   Findings        -> the same entities as a searchable table
//   Entity detail   -> one entity: how it moved, how unusual that is, ranked drivers inside it
//   Drill-down      -> every segment of every view inside that entity, drill as deep as you like
//   KPI tree        -> how the KPI is built and which branch moved (whole scope or one entity)
//
// Every number comes from /api/rca/* (exact splits, checked on each response). Nothing is typed in here.

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchRcaCause, fetchRcaLens, fetchRcaOptions } from "@/lib/rca-api";
import { useFilters } from "@/lib/filter-context";
import type { RcaLens, RcaOptions, TopCause } from "@/lib/rca-types";
import CommandCenter from "./CommandCenter";
import DrillDownView from "./DrillDownView";
import EntityDetail from "./EntityDetail";
import FindingsExplorer from "./FindingsExplorer";
import { type ControlsProps, ErrorBox } from "./RcaShell";
import TreeScreen from "./TreeScreen";

const NO_CAUSES: Record<string, TopCause | null> = {};

type View =
  | { kind: "home" }
  | { kind: "explorer" }
  | { kind: "entity"; dim: string; segment: string }
  | { kind: "drill"; path: string[] }
  | { kind: "tree"; path: string[] };

export default function RcaPage() {
  const { filters } = useFilters();
  const [options, setOptions] = useState<RcaOptions | null>(null);
  const [optErr, setOptErr] = useState<string | null>(null);
  const [metric, setMetric] = useState("");
  const [month, setMonth] = useState("");
  const [compare, setCompare] = useState("prior_month");
  const [lensKey, setLensKey] = useState("unit");
  const [stack, setStack] = useState<View[]>([{ kind: "home" }]);
  const view = stack[stack.length - 1];

  const [lens, setLens] = useState<RcaLens | null>(null);
  const [lensDone, setLensDone] = useState<{ key: string; err: string | null } | null>(null);
  // Top drivers are stored together with the entity list they belong to, so a new list starts with none.
  const [causeState, setCauseState] = useState<{ lens: RcaLens | null; map: Record<string, TopCause | null> }>({ lens: null, map: {} });
  const causes = causeState.lens === lens ? causeState.map : NO_CAUSES;
  const causeRun = useRef(0);

  // ---- navigation: a tiny stack so "Back" always returns to where you came from
  const go = useCallback((v: View) => setStack((s) => [...s, v]), []);
  const back = useCallback(() => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)), []);
  const home = useCallback(() => setStack([{ kind: "home" }]), []);
  const explorer = useCallback(() => setStack((s) => {
    const i = s.findIndex((v) => v.kind === "explorer");
    return i >= 0 ? s.slice(0, i + 1) : [...s, { kind: "explorer" }];
  }), []);

  useEffect(() => {
    fetchRcaOptions().then((o) => {
      setOptions(o);
      setMetric(o.metrics[0].key);
      setMonth(o.default_month);
      setCompare(o.metrics[0].compares[0].key);
    }).catch((e) => setOptErr(String(e.message ?? e)));
  }, []);

  const m = options?.metrics.find((x) => x.key === metric);
  const monthInfo = options?.months.find((x) => x.value === month);
  const compareOk = useCallback((key: string) =>
    key === "prior_month" ? monthInfo?.has_prior_month !== false
    : key === "same_month_last_year" ? monthInfo?.has_same_month_last_year !== false : true, [monthInfo]);

  // Keep the comparison and the view valid when the metric or month changes. These are adjusted while rendering
  // (each only fires when the current choice is no longer valid), not in effects.
  if (m) {
    const ok = m.compares.filter((c) => compareOk(c.key));
    if (ok.length && !ok.some((c) => c.key === compare)) setCompare(ok[0].key);
  }
  if (m && lens) {
    const valid = lens.lenses.map((l) => l.key);
    if (valid.length && !valid.includes(lensKey)) setLensKey(valid.includes("unit") ? "unit" : valid[0]);
  }
  if (m && compare && !m.dims.some((d) => d.key === lensKey)) setLensKey(m.dims.some((d) => d.key === "unit") ? "unit" : m.dims[0].key);

  // ---- load the entity list for the current controls (home + findings share it)
  // `lensReq` identifies the request the current controls call for (null = nothing to load right now). The page is
  // "loading" until that request has answered; the answer is recorded only when a response arrives.
  const showsLens = view.kind === "home" || view.kind === "explorer";
  const lensReady = !!(options && metric && month && m && compare && showsLens
    && m.compares.some((c) => c.key === compare) && compareOk(compare));
  const lensReq = lensReady ? [metric, month, compare, lensKey, JSON.stringify(filters)].join("#") : null;
  const lensLoading = lensReq !== null && lensDone?.key !== lensReq;
  const lensErr = lensReq !== null && lensDone?.key === lensReq ? lensDone.err : null;
  useEffect(() => {
    if (lensReq === null) return;
    const ac = new AbortController();
    fetchRcaLens({ metric, month, compare }, filters, lensKey, ac.signal)
      .then((d) => { setLens(d); setLensDone({ key: lensReq, err: null }); })
      .catch((e) => { if (e.name !== "AbortError") setLensDone({ key: lensReq, err: String(e.message ?? e) }); });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lensReq]);

  // ---- each card's top driver arrives separately so the cards themselves show at once
  useEffect(() => {
    if (!lens || !options) return;
    const run = ++causeRun.current;
    const ac = new AbortController();
    const n = options.home_cards ?? 8;
    const put = (segment: string, v: TopCause | null) =>
      setCauseState((s) => ({ lens, map: { ...(s.lens === lens ? s.map : {}), [segment]: v } }));
    lens.entities.slice(0, n).forEach((e) => {
      fetchRcaCause({ metric: lens.metric.key, month: lens.period.month, compare: lens.compare.key }, filters, lens.lens.key, e.segment, ac.signal)
        .then((r) => { if (run === causeRun.current) put(e.segment, r.top_cause); })
        .catch(() => { if (run === causeRun.current && !ac.signal.aborted) put(e.segment, null); });
    });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lens]);

  const controls: ControlsProps | null = options && m ? {
    options, metric, month, compare, lensKey, views: null,
    onMetric: (k) => { setMetric(k); const nm = options.metrics.find((x) => x.key === k)!; if (!nm.compares.some((c) => c.key === compare)) setCompare(nm.compares[0].key); },
    onMonth: setMonth, onCompare: setCompare, onLens: setLensKey, compareOk,
  } : null;

  if (optErr) return <ErrorBox message={`Could not load the RCA options: ${optErr}`} />;
  if (!options || !m || !controls) return <div className="h-40 animate-pulse rounded-lg bg-slate-200" />;

  const params = { metric, month, compare };

  switch (view.kind) {
    case "explorer":
      return <FindingsExplorer options={options} controls={controls} lens={lens} loading={lensLoading} error={lensErr}
                               onHome={home} onOpenEntity={(segment) => go({ kind: "entity", dim: lensKey, segment })} />;
    case "entity":
      return <EntityDetail options={options} params={params} filters={filters} dim={view.dim} segment={view.segment} hasTree={m.has_tree}
                           onHome={home} onExplorer={explorer}
                           onDrill={(path) => go({ kind: "drill", path })} onTree={(path) => go({ kind: "tree", path })} />;
    case "drill":
      return <DrillDownView params={params} filters={filters} initialPath={view.path} hasTree={m.has_tree}
                            onHome={home} onBack={back} onTree={(path) => go({ kind: "tree", path })} />;
    case "tree":
      return <TreeScreen options={options} params={params} filters={filters} path={view.path} onHome={home} onBack={back} />;
    default:
      return <CommandCenter options={options} controls={controls} lens={lens} loading={lensLoading} error={lensErr} causes={causes}
                            hasTree={m.has_tree}
                            onOpenEntity={(segment) => go({ kind: "entity", dim: lensKey, segment })}
                            onExplorer={() => go({ kind: "explorer" })} onTree={() => go({ kind: "tree", path: [] })} />;
  }
}
