"use client";

import { useEffect, useMemo, useState } from "react";
import { inrFull } from "@/lib/format";
import { fetchPredictStatus } from "@/lib/predict-api";
import type { PlanSettings, PredictOptions, StatusDetail } from "@/lib/predict-types";
import type { FilterState } from "@/lib/types";
import Modal from "./Modal";
import PlanTable from "./PlanTable";
import { statusCols } from "./columns";
import { num, statusColor, type OnPickItem } from "./shared";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

// Every item x unit line behind one slice of the stock-health donut. The count and
// stock value shown here are the same numbers the donut shows for that slice.
export default function StatusModal({ status, filters, plan, options, onPick, onClose }: {
  status: string; filters: FilterState; plan: PlanSettings; options: PredictOptions; onPick: OnPickItem; onClose: () => void;
}) {
  const [res, setRes] = useState<{ status: string; data: StatusDetail | null; error: string | null } | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    fetchPredictStatus(filters, plan, status, ac.signal)
      .then((d) => setRes({ status, data: d, error: null }))
      .catch((e) => { if (e.name !== "AbortError") setRes({ status, data: null, error: String(e.message ?? e) }); });
    return () => ac.abort();
  }, [filters, plan, status]);

  const d = res && res.status === status ? res.data : null;
  const error = res && res.status === status ? res.error : null;
  const cols = useMemo(() => statusCols(status, options), [status, options]);

  return (
    <Modal wide onClose={onClose} title={`${status}${d ? ` · ${num(d.total)} lines` : ""}`} subtitle={d?.rule}>
      {error && <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
      {!d && !error && <div className="h-40 animate-pulse rounded bg-slate-100" />}
      {d && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
            <i className="h-3 w-3 rounded-sm" style={{ background: statusColor(status) }} />
            {d.help}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Lines" value={num(d.total)} />
            {status !== "No stock record" && <Stat label="Stock value" value={inrFull(d.stock_value)} />}
            {(status === "Critical" || status === "Order soon") && <Stat label="Order value" value={inrFull(d.order_value)} />}
            {(status === "Excess" || status === "No recent usage") && <Stat label="Excess value" value={inrFull(d.excess_value)} />}
          </div>
          <PlanTable rows={d.rows} cols={cols} onPick={onPick} total={d.total} more={d.more} emptyText="No lines in this status." />
        </div>
      )}
    </Modal>
  );
}
