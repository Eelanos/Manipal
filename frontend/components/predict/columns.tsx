import type { PredictOptions } from "@/lib/predict-types";
import { inrFull } from "@/lib/format";
import type { Col } from "./PlanTable";
import { StatusPill } from "./PlanTable";
import { coverText, dec1, num } from "./shared";

// Column sets for the two tables. `opts` supplies the horizon used to label capped cover.
const item: Col = { key: "item", label: "Item", render: (r) => <span className="font-medium text-slate-900">{r.item_name}</span>, sort: (r) => r.item_name };
const unit: Col = { key: "unit", label: "Unit", render: (r) => r.unit_name, sort: (r) => r.unit_name };
const status: Col = { key: "status", label: "Status", render: (r) => <StatusPill status={r.status} />, sort: (r) => r.status };
const onHand: Col = { key: "on_hand", label: "Usable stock", align: "right", render: (r) => num(r.on_hand), sort: (r) => r.on_hand };
const usage: Col = { key: "usage", label: "Daily usage", align: "right", render: (r) => dec1(r.daily_usage), sort: (r) => r.daily_usage };

const cover = (opts: PredictOptions | null): Col => ({
  key: "cover", label: "Days of cover", align: "right",
  render: (r) => coverText(r.cover_days, r.cover_capped, opts),
  sort: (r) => r.cover_days ?? Number.MAX_SAFE_INTEGER,
});

const stockValue: Col = { key: "sv", label: "Stock value", align: "right", render: (r) => inrFull(r.stock_value), sort: (r) => r.stock_value };
const onOrder: Col = { key: "on_order", label: "On order", align: "right", render: (r) => num(r.on_order), sort: (r) => r.on_order };

// Columns for the list behind a donut slice: the numbers that explain that status.
export const statusCols = (status: string, opts: PredictOptions | null): Col[] => {
  if (status === "Critical" || status === "Order soon") return reorderCols(opts).filter((c) => c.key !== "status");
  if (status === "Excess") return [item, unit, onHand, usage, cover(opts), stockValue, ...excessCols(opts).slice(5)];
  if (status === "No stock record") return [item, unit, usage];
  return [item, unit, onHand, onOrder, usage, cover(opts), stockValue];
};

export const reorderCols = (opts: PredictOptions | null): Col[] => [
  item, unit, status, onHand,
  { key: "on_order", label: "On order", align: "right", render: (r) => num(r.on_order), sort: (r) => r.on_order },
  usage, cover(opts),
  { key: "rop", label: "Reorder point", align: "right", render: (r) => num(r.reorder_point), sort: (r) => r.reorder_point },
  { key: "qty", label: "Order qty", align: "right", render: (r) => <b className="text-slate-900">{num(r.order_qty)}</b>, sort: (r) => r.order_qty },
  { key: "val", label: "Order value", align: "right", render: (r) => inrFull(r.order_value), sort: (r) => r.order_value },
];

export const excessCols = (opts: PredictOptions | null): Col[] => [
  item, unit, onHand, usage, cover(opts),
  { key: "exq", label: "Excess qty", align: "right", render: (r) => num(r.excess_qty), sort: (r) => r.excess_qty },
  { key: "exv", label: "Excess value", align: "right", render: (r) => <b className="text-slate-900">{inrFull(r.excess_value)}</b>, sort: (r) => r.excess_value },
];
