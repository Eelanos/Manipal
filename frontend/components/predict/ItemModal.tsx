"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { inrFull } from "@/lib/format";
import { fetchPredictItem } from "@/lib/predict-api";
import type { ItemDetail, PredictOptions } from "@/lib/predict-types";
import type { FilterState } from "@/lib/types";
import Modal from "./Modal";
import { StatusPill } from "./PlanTable";
import { TOOLTIP, coverText, dateText, dayLabel, dec1, num } from "./shared";

function Fact({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2" title={hint}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

export default function ItemModal({ target, filters, options, onClose }: {
  target: { item_id: string; unit_id: string }; filters: FilterState;
  options: PredictOptions | null; onClose: () => void;
}) {
  // Answer tagged with its request, so a previous item is never shown for a new one.
  const key = useMemo(() => JSON.stringify([filters, target]), [filters, target]);
  const [res, setRes] = useState<{ key: string; d: ItemDetail | null; err: string | null } | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    fetchPredictItem(filters, target.item_id, target.unit_id, ac.signal)
      .then((d) => setRes({ key, d, err: null }))
      .catch((e) => { if (e.name !== "AbortError") setRes({ key, d: null, err: String(e.message ?? e) }); });
    return () => ac.abort();
  }, [filters, target, key]);
  const cur = res && res.key === key ? res : null;
  const d = cur?.d ?? null;
  const err = cur?.err ?? null;

  const f = d?.facts;
  const lead = Number(d?.settings.lead_days);
  const horizon = Number(d?.settings.expiry_horizon_days);
  const arrive = d && f && f.on_order > 0 ? d.projection.find((p) => p.day === lead)?.date : undefined;
  const orderBy = d && f?.order_by ? d.projection.find((p) => p.date === f.order_by)?.date : undefined;

  return (
    <Modal title={d ? `${d.item_name} · ${d.unit_name}` : "Loading…"} wide onClose={onClose}
           subtitle={d ? `${d.group} · stock as of ${dateText(d.as_of)}` : undefined}>
      {err && <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{err}</p>}
      {!d && !err && <div className="h-64 animate-pulse rounded-lg bg-slate-200" />}
      {d && f && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill status={d.status} />
            <span className="text-sm text-slate-600">{d.status_help}</span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Fact label="Usable stock" value={num(f.on_hand)} hint="Stock on the shelf at the snapshot date that has not expired" />
            <Fact label="On order" value={num(f.on_order)} hint="Already ordered and on its way, not yet received (stock in transit)" />
            <Fact label="Daily usage" value={dec1(f.daily_usage)} hint="Average units used per day over the usage window" />
            {f.expired_qty > 0 && <Fact label="Expired (not usable)" value={num(f.expired_qty)} />}
            <Fact label="Days of cover" value={coverText(f.cover_days, f.cover_capped, options)} hint="Days until the usable stock on hand is used up (open orders not counted)" />
            <Fact label="Reorder point" value={num(f.reorder_point)} hint="Usage during delivery time + safety buffer. If stock + on order falls below this, an order is needed" />
            <Fact label="Suggested order" value={f.order_qty > 0 ? `${num(f.order_qty)} units` : "None needed"} hint="Units to order now to cover delivery + buffer + order-cover days, after counting stock and on order" />
            <Fact label="Order value" value={f.order_qty > 0 ? inrFull(f.order_value) : "₹0"} hint="Suggested order × unit cost" />
            <Fact label="Order by"
                  value={f.order_qty > 0 ? "Now" : f.order_by ? dateText(f.order_by) : "Not needed soon"}
                  hint="The date when stock + on order is expected to fall to the reorder point" />
          </div>

          <div className="rounded-lg border border-slate-300 bg-canvas p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-nav">How this was worked out</p>
            <ul className="space-y-1">{d.explain.map((t, i) => <li key={i} className="text-sm text-slate-700">- {t}</li>)}</ul>
          </div>

          <section>
            <h4 className="text-sm font-semibold text-slate-900">Stock projection</h4>
            <p className="mb-2 text-xs text-slate-500">
              Starts at usable stock, falls with expected daily usage, and jumps up when an open order arrives. Once it drops below the dashed reorder-point line, an order is due.
            </p>
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={d.projection} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 11 }} minTickGap={28} />
                <YAxis tick={{ fontSize: 11 }} width={48} />
                <Tooltip {...TOOLTIP} labelFormatter={(l) => dateText(String(l))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="stock" name="Expected stock" stroke="#3d6479" fill="#3d6479" fillOpacity={0.2} />
                <Line type="monotone" dataKey="reorder_point" name="Reorder point" stroke="#e08a1e" strokeDasharray="5 4" dot={false} />
                {orderBy && f.order_in_days !== null && f.order_in_days > 0 && (
                  <ReferenceLine x={orderBy} stroke="#c0392b" label={{ value: "Order by", position: "top", fontSize: 10, fill: "#c0392b" }} />
                )}
                {arrive && <ReferenceLine x={arrive} stroke="#2a9d8f" strokeDasharray="3 3" label={{ value: "Open order arrives", position: "top", fontSize: 10, fill: "#2a9d8f" }} />}
              </ComposedChart>
            </ResponsiveContainer>
          </section>

          <section>
            <h4 className="text-sm font-semibold text-slate-900">Batches and expiry</h4>
            {d.batches.length === 0 ? (
              <p className="py-3 text-sm text-slate-500">No stock on hand, so no batches.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="mt-1 w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>{["Batch", "Expiry", "Days left", "Qty", "Used before expiry", "At risk (qty)", "At risk (₹)"].map((h, i) => (
                      <th key={h} className={`px-3 py-2 font-medium ${i < 2 ? "text-left" : "text-right"}`}>{h}</th>))}</tr>
                  </thead>
                  <tbody className="text-slate-700">
                    {d.batches.map((b) => (
                      <tr key={b.batch} className="border-t border-slate-100">
                        <td className="px-3 py-2 text-slate-800">{b.batch}</td>
                        <td className="px-3 py-2 text-slate-700">{dateText(b.expiry)}{b.state === "expired" && <span className="ml-2 text-xs font-medium text-red-600">Expired</span>}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{b.days_to_expiry <= 0 ? "—" : num(b.days_to_expiry)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{num(b.qty)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{b.state === "expired" ? "—" : b.state === "ok" ? <span className="text-xs text-slate-500" title={`Expires after the ${horizon}-day look-ahead, so it is not assessed yet`}>Beyond {horizon} days</span> : num(b.expected_used)}</td>
                        <td className={`px-3 py-2 text-right tabular-nums ${b.at_risk_qty > 0 ? "font-semibold text-red-600" : ""}`}>{b.state === "ok" ? "–" : num(b.at_risk_qty)}</td>
                        <td className={`px-3 py-2 text-right tabular-nums ${b.at_risk_value > 0 ? "font-semibold text-red-600" : ""}`}>{b.state === "ok" ? "–" : inrFull(b.at_risk_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <ul className="space-y-0.5 text-[11px] text-slate-500">
            <li>Used before expiry = units expected to be used before the batch expires, oldest expiry first. At risk = quantity − used. Batches expiring after {horizon} days are not assessed yet (shown as –).</li>
            {d.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}
    </Modal>
  );
}
