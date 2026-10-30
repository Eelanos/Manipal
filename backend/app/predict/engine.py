"""
Predictive Analysis engine - rule-based demand & replenishment planning.

NO machine learning. Every figure is a plain formula on the same Parquet data
the dashboards read, through the same filter contract, so a person can verify
any number with a calculator.

THE FORMULAS (all "per item per unit" unless stated)
----------------------------------------------------
  window            the last N whole months ending at the stock snapshot
  daily usage       total quantity used in the window / days in the window
  season factor     (month-of-year pattern seen in complete past years) /
                    (the same pattern averaged over the window) -> 1.0 if off
  demand over D     daily usage x (sum of the season factors for the next D days)
  days of cover     days until cumulative demand reaches the stock on hand
  reorder point     demand over (delivery time + safety buffer)
  order-up-to       demand over (delivery time + safety buffer + plan days)
  position          on hand + on order (open purchase orders)
  order quantity    order-up-to - position   (only when position < reorder point)
  excess            on hand - demand over (max days of cover)
  expiry at risk    FIFO: batches are used earliest-expiry first; whatever the
                    expected usage cannot reach before expiry is at risk
  forecast range    how far the SAME method missed in past months (10th..90th
                    percentile of actual/forecast) - an honest range, not a guess

Planning (stock, orders, reorder, excess, expiry) works at UNIT level because
stock is not tracked by department. The Department filter therefore narrows
only the DEMAND views (forecast chart, expected-demand KPI) - the page says so.

Only reads the DataStore; nothing here can alter another module's behaviour.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from app.config import AS_OF_DATE, DATA_END, DATA_START
from app.data_loader import DataStore
from app.filters import ALL, Filters, apply
from app.formatting import inr_compact, pct, qty_compact
from app.predict import params as P
from app.predict.params import Params
from app.schemas import Kpi


class PredictError(ValueError):
    """User-facing problem (unknown item, etc.). The router maps it to HTTP 400/404."""


_EPS = 1e-9   # numerical floor so cumulative demand stays strictly increasing


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def _num(x) -> float | None:
    """JSON-safe number: NaN/Inf -> None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _r(x, nd: int = 2) -> float | None:
    v = _num(x)
    return None if v is None else round(v, nd)


def _days_in_month(ts: pd.Timestamp) -> int:
    return calendar.monthrange(ts.year, ts.month)[1]


def _month_index(first: pd.Timestamp, last: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(first.to_period("M").to_timestamp(), last.to_period("M").to_timestamp(), freq="MS")


def _monthly(df: pd.DataFrame, col: str, idx: pd.DatetimeIndex) -> pd.Series:
    """Sum `col` by calendar month onto a complete month index (gaps = 0)."""
    if df.empty:
        return pd.Series(0.0, index=idx)
    s = df.groupby(df["Date"].dt.to_period("M").dt.to_timestamp())[col].sum()
    return s.reindex(idx, fill_value=0.0).astype(float)


def _window(win_end: pd.Timestamp, months: int) -> tuple[pd.Timestamp, int]:
    """(first day, number of days) of the `months` whole months ending on win_end."""
    start = (win_end + pd.Timedelta(days=1)) - pd.DateOffset(months=months)
    return start, int((win_end - start).days) + 1


# ----------------------------------------------------------------------------
# seasonality
# ----------------------------------------------------------------------------
def season_index(monthly: pd.Series, upto: int) -> np.ndarray | None:
    """
    Month-of-year index (12 values, mean 1.0) from COMPLETE calendar years only,
    using months [0..upto] of `monthly` (never the future).

    For every complete year: each month's daily rate / that year's average daily
    rate. Average across years, then scale so the 12 values average 1.0.
    Returns None when no complete year exists (or the usage is all zero).
    """
    m = monthly.iloc[: upto + 1]
    ratios = []
    for year in sorted({d.year for d in m.index}):
        part = m[m.index.year == year]
        if len(part) != 12:                       # partial year -> skip
            continue
        days = np.array([_days_in_month(d) for d in part.index], dtype=float)
        year_rate = part.sum() / days.sum()
        if year_rate <= 0:
            continue
        ratios.append((part.values / days) / year_rate)
    if not ratios:
        return None
    idx = np.mean(ratios, axis=0)
    mean = idx.mean()
    if not np.isfinite(mean) or mean <= 0:
        return None
    return idx / mean


def _daily_factors(idx12: np.ndarray | None, win_start: pd.Timestamp, win_end: pd.Timestamp,
                   first_day: pd.Timestamp, n_days: int) -> np.ndarray:
    """
    Season factor for each of the n_days after `first_day - 1`:
    idx[month of that day] / (days-weighted mean idx over the window).
    No seasonality -> all ones.
    """
    if idx12 is None:
        return np.ones(n_days)
    wdays = pd.date_range(win_start, win_end, freq="D")
    wmean = idx12[wdays.month.values - 1].mean()
    if not np.isfinite(wmean) or wmean <= 0:
        return np.ones(n_days)
    days = pd.date_range(first_day, periods=n_days, freq="D")
    return np.maximum(idx12[days.month.values - 1] / wmean, _EPS)


def _cum(factors: np.ndarray) -> np.ndarray:
    """cum[d] = demand multiplier over the next d days; cum[0] = 0."""
    return np.concatenate([[0.0], np.cumsum(factors)])


def _at(cum: np.ndarray, d) -> np.ndarray:
    """cum evaluated at (possibly fractional) day counts, clipped to the horizon."""
    d = np.clip(np.asarray(d, dtype=float), 0, len(cum) - 1)
    return np.interp(d, np.arange(len(cum)), cum)


def _inverse(cum: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Days until cumulative multiplier reaches `target` (stock / daily usage).
    Returns (days, capped) - capped True where the answer is beyond the horizon.
    """
    target = np.asarray(target, dtype=float)
    capped = target >= cum[-1]
    days = np.interp(target, cum, np.arange(len(cum)))
    days = np.where(capped, len(cum) - 1, days)
    return days, capped


# ----------------------------------------------------------------------------
# the plan (one row per item x unit)
# ----------------------------------------------------------------------------
@dataclass
class Plan:
    params: Params
    snapshot: pd.Timestamp
    win_start: pd.Timestamp
    win_end: pd.Timestamp
    window_days: int
    cum: np.ndarray                  # planning (quantity) season multipliers
    season_used: bool
    season_note: str
    lines: pd.DataFrame              # one row per item x unit
    batches: pd.DataFrame            # one row per batch with expiry analysis
    scope_empty: bool


_LINE_COLS = ["Unit_ID", "Item_ID"]


def _scope_frames(store: DataStore, f: Filters):
    """
    The filtered source tables. `f_plan` ignores Department (stock isn't held by
    department) and Period (planning always looks from the latest snapshot).
    """
    f_all = replace(f, date_from=DATA_START, date_to=DATA_END)
    f_plan = replace(f_all, department=ALL)
    return f_all, f_plan


def _plan_consumption(store: DataStore, f_plan: Filters) -> pd.DataFrame:
    """
    Usage for planning. Stock and purchase rows always carry the item's MASTER
    Stock Take Group, but ~2% of consumption rows are tagged with another group.
    Filtering usage by that row tag would give items with usage but no stock
    (false stock-outs), so planning selects items by their master group instead.
    """
    cons = apply(store.consumption, replace(f_plan, stock_take_group=ALL), "Date")
    if f_plan.stock_take_group != ALL:
        ids = store.items.loc[store.items["Stock Take Group"] == f_plan.stock_take_group, "Item_ID"]
        cons = cons[cons["Item_ID"].isin(ids)]
    return cons


def _snapshot(store: DataStore) -> pd.Timestamp:
    inv = store.inventory
    inv = inv[inv["Date"] <= pd.Timestamp(AS_OF_DATE)]
    if inv.empty:
        raise PredictError("No inventory snapshot is available.")
    return pd.Timestamp(inv["Date"].max()).normalize()


def _window_end(snapshot: pd.Timestamp) -> pd.Timestamp:
    """Whole months only: the snapshot if it is a month end, else the previous month end."""
    if snapshot == snapshot + pd.offsets.MonthEnd(0):
        return snapshot
    return (snapshot.to_period("M").to_timestamp() - pd.Timedelta(days=1)).normalize()


def _cache_key(store: DataStore, f: Filters, p: Params) -> tuple:
    return (id(store), len(store.consumption), tuple(sorted(f.as_dict().items())), p.key())


_PLAN_CACHE: dict[tuple, Plan] = {}
_CACHE_MAX = 64


def compute_plan(store: DataStore, f: Filters, p: Params) -> Plan:
    key = _cache_key(store, f, p)
    hit = _PLAN_CACHE.get(key)
    if hit is not None:
        return hit
    plan = _compute_plan(store, f, p)
    if len(_PLAN_CACHE) >= _CACHE_MAX:
        _PLAN_CACHE.pop(next(iter(_PLAN_CACHE)))
    _PLAN_CACHE[key] = plan
    return plan


def clear_cache() -> None:
    _PLAN_CACHE.clear()


def _compute_plan(store: DataStore, f: Filters, p: Params) -> Plan:
    snapshot = _snapshot(store)
    win_end = _window_end(snapshot)
    win_start, window_days = _window(win_end, p.window_months)
    _, f_plan = _scope_frames(store, f)

    cons = _plan_consumption(store, f_plan)
    cons = cons[cons["Date"] <= win_end]

    # --- seasonality (quantity, whole scope, complete years up to win_end) ----
    first_month = store.consumption["Date"].min()
    midx = _month_index(first_month, win_end)
    qty_month = _monthly(cons, "Qty", midx)
    idx12 = season_index(qty_month, len(midx) - 1) if p.seasonality else None
    if not p.seasonality:
        season_note = "Seasonality adjustment is off."
    elif idx12 is None:
        season_note = "Seasonality needs one full year of history; not available, so no adjustment is applied."
    else:
        season_note = "Usage is adjusted for the month-of-year pattern seen in past years (measured on the selected scope)."
    factors = _daily_factors(idx12, win_start, win_end, snapshot + pd.Timedelta(days=1), P.HORIZON_DAYS)
    cum = _cum(factors)

    # --- usage per item x unit in the window -----------------------------------
    w = cons[(cons["Date"] >= win_start) & (cons["Date"] <= win_end)]
    usage = (w.groupby(_LINE_COLS)["Qty"].sum() / window_days).rename("rate")

    # --- stock at the snapshot ---------------------------------------------------
    inv_all = apply(store.inventory, replace(f_plan, date_from=snapshot.date(), date_to=snapshot.date()), "Date")
    # Expired stock cannot be used or sold: it is NOT on hand for planning (it is reported as expired).
    live = inv_all["Expiry_Date"].isna() | (inv_all["Expiry_Date"] > snapshot)
    inv_all = inv_all.assign(_q=inv_all["Stock_Qty"].where(live, 0.0), _v=inv_all["Stock_Value"].where(live, 0.0),
                             _xq=inv_all["Stock_Qty"].where(~live, 0.0))
    stock = inv_all.groupby(_LINE_COLS).agg(on_hand=("_q", "sum"), stock_value=("_v", "sum"), expired_qty=("_xq", "sum"))

    # --- open purchase orders ----------------------------------------------------
    po = apply(store.purchase, f_plan, "PO_Date")
    po = po[(po["Status"] == P.OPEN_PO_STATUS) & (po["PO_Date"] <= snapshot)]
    on_order = po.groupby(_LINE_COLS)["Qty"].sum().rename("on_order")

    lines = pd.concat([usage, stock, on_order], axis=1).reset_index()
    # A line with usage but NO inventory row on the snapshot date is a data gap, not a proven
    # stock-out (the stock table has gaps: such items are often used the same month). Not planned.
    lines["has_record"] = lines["on_hand"].notna() if "on_hand" in lines else False
    for c in ("rate", "on_hand", "stock_value", "on_order", "expired_qty"):
        lines[c] = lines[c].fillna(0.0) if c in lines else 0.0
    lines = lines[(lines["rate"] > 0) | (lines["on_hand"] > 0) | (lines["on_order"] > 0)].reset_index(drop=True)

    if lines.empty:
        return Plan(p, snapshot, win_start, win_end, window_days, cum, idx12 is not None,
                    season_note, _empty_lines(), _empty_batches(), True)

    # --- master data -------------------------------------------------------------
    items = store.items.set_index("Item_ID")
    lines["item_name"] = lines["Item_ID"].map(items["Item_Name"])
    lines["group"] = lines["Item_ID"].map(items["Stock Take Group"])
    lines["unit_price"] = lines["Item_ID"].map(items["Unit_Price"]).fillna(0.0)
    unit_names = store.units.set_index("Unit_ID")["Unit_Name"]
    lines["unit_name"] = lines["Unit_ID"].map(unit_names).fillna(lines["Unit_ID"])

    rate = lines["rate"].to_numpy()
    on_hand = lines["on_hand"].to_numpy()
    position = on_hand + lines["on_order"].to_numpy()
    safe_rate = np.where(rate > 0, rate, np.nan)

    # --- the formulas ------------------------------------------------------------
    ld, bf, pl = p.lead_days, p.buffer_days, p.plan_days
    cover, cover_capped = _inverse(cum, on_hand / safe_rate)
    pos_cover, _ = _inverse(cum, position / safe_rate)
    rec = lines["has_record"].to_numpy(dtype=bool)
    planned = (rate > 0) & rec
    cover = np.where(planned, cover, np.nan)
    pos_cover = np.where(planned, pos_cover, np.nan)
    cover_capped = np.where(planned, cover_capped, False)

    rop = rate * _at(cum, ld + bf)
    out_to = np.ceil(rate * _at(cum, ld + bf + pl))          # whole units
    need_order = planned & (position < rop)
    order_qty = np.where(need_order, np.maximum(0.0, out_to - position), 0.0)
    excess_qty = np.maximum(0.0, on_hand - rate * _at(cum, p.max_cover_days))
    excess_qty = np.where(on_hand > 0, np.ceil(excess_qty), 0.0)
    # order within how many days (0 = now): when position falls to the reorder point
    order_in = np.where(planned, np.maximum(0.0, pos_cover - (ld + bf)), np.nan)

    status = np.full(len(lines), P.STATUS_HEALTHY, dtype=object)
    status[(excess_qty > 0)] = P.STATUS_EXCESS
    status[need_order] = P.STATUS_ORDER_SOON
    status[need_order & (cover < ld)] = P.STATUS_CRITICAL
    status[(rate <= 0) & (on_hand > 0)] = P.STATUS_NO_USAGE
    status[(rate > 0) & ~rec] = P.STATUS_NO_RECORD
    # a line with no stock, no usage but an open PO is simply healthy

    unit_cost = np.where(on_hand > 0, lines["stock_value"].to_numpy() / np.where(on_hand > 0, on_hand, 1), lines["unit_price"].to_numpy())
    lines["cover_days"] = cover
    lines["position_cover_days"] = pos_cover        # days covered by stock + open orders (tie-break)
    lines["cover_capped"] = cover_capped
    lines["reorder_point"] = rop
    lines["order_up_to"] = out_to
    lines["position"] = position
    lines["order_qty"] = order_qty
    lines["order_value"] = order_qty * lines["unit_price"].to_numpy()
    lines["order_in_days"] = order_in
    lines["excess_qty"] = excess_qty
    lines["excess_value"] = excess_qty * unit_cost
    lines["status"] = status
    lines["unit_cost"] = unit_cost

    batches = _batch_risk(store, f_plan, snapshot, lines, cum, p)
    risk = batches[batches["state"] == "expiring"].groupby(_LINE_COLS)["risk_value"].sum().rename("expiry_risk_value")
    expired = batches[batches["state"] == "expired"].groupby(_LINE_COLS)["risk_value"].sum().rename("expired_value")
    lines = lines.merge(risk.reset_index(), on=_LINE_COLS, how="left").merge(expired.reset_index(), on=_LINE_COLS, how="left")
    lines[["expiry_risk_value", "expired_value"]] = lines[["expiry_risk_value", "expired_value"]].fillna(0.0)

    return Plan(p, snapshot, win_start, win_end, window_days, cum, idx12 is not None, season_note, lines, batches, False)


def _empty_lines() -> pd.DataFrame:
    cols = (_LINE_COLS + ["rate", "on_hand", "stock_value", "on_order", "item_name", "group", "unit_price",
                          "unit_name", "cover_days", "cover_capped", "reorder_point", "order_up_to", "position",
                          "order_qty", "order_value", "order_in_days", "excess_qty", "excess_value", "status",
                          "unit_cost", "expiry_risk_value", "expired_value", "position_cover_days", "expired_qty"])
    return pd.DataFrame({c: pd.Series(dtype=object if c in ("status", "item_name", "group", "unit_name", "Unit_ID", "Item_ID") else float) for c in cols})


def _empty_batches() -> pd.DataFrame:
    cols = _LINE_COLS + ["Batch_No", "Expiry_Date", "qty", "value", "days_to_expiry", "used_qty", "risk_qty", "risk_value", "state"]
    return pd.DataFrame({c: pd.Series(dtype=object) for c in cols})


def _batch_risk(store: DataStore, f_plan: Filters, snapshot: pd.Timestamp, lines: pd.DataFrame,
                cum: np.ndarray, p: Params) -> pd.DataFrame:
    """
    FIFO expiry check. Within each item x unit, batches are consumed earliest
    expiry first. By a batch's expiry day, expected usage is rate x cum[days].
    The part of that usage not already claimed by earlier batches is what this
    batch can use; whatever is left is at risk.
    """
    inv = apply(store.inventory, replace(f_plan, date_from=snapshot.date(), date_to=snapshot.date()), "Date")
    if inv.empty:
        return _empty_batches()
    b = (inv.groupby(_LINE_COLS + ["Batch_No", "Expiry_Date"], dropna=False)
            .agg(qty=("Stock_Qty", "sum"), value=("Stock_Value", "sum")).reset_index())
    b = b[b["qty"] > 0].copy()
    b["days_to_expiry"] = (b["Expiry_Date"] - snapshot).dt.days
    rate_map = lines.set_index(_LINE_COLS)["rate"]
    b["rate"] = pd.MultiIndex.from_frame(b[_LINE_COLS]).map(rate_map).to_numpy(dtype=float)
    b["rate"] = np.nan_to_num(b["rate"], nan=0.0)
    b["state"] = np.where(b["days_to_expiry"] <= 0, "expired",
                          np.where(b["days_to_expiry"] <= p.expiry_horizon_days, "expiring", "ok"))

    live = b[b["days_to_expiry"] > 0].sort_values(_LINE_COLS + ["days_to_expiry"]).copy()
    live["earlier"] = live.groupby(_LINE_COLS)["qty"].cumsum() - live["qty"]
    usable_by = live["rate"].to_numpy() * _at(cum, live["days_to_expiry"].to_numpy())
    live["used_qty"] = np.clip(usable_by - live["earlier"].to_numpy(), 0, live["qty"].to_numpy())
    live["risk_qty"] = live["qty"] - live["used_qty"]

    b["used_qty"] = 0.0
    b["risk_qty"] = np.where(b["state"] == "expired", b["qty"], 0.0)
    b.loc[live.index, "used_qty"] = live["used_qty"]
    b.loc[live.index, "risk_qty"] = live["risk_qty"]
    b["risk_qty"] = np.where(b["state"] == "ok", 0.0, b["risk_qty"])
    per_unit = np.where(b["qty"] > 0, b["value"] / b["qty"], 0.0)
    b["risk_value"] = b["risk_qty"] * per_unit
    return b.drop(columns=["rate"]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# forecast (value) + honest range from back-testing the same method
# ----------------------------------------------------------------------------
def _forecast_from(monthly: pd.Series, origin: int, window_months: int, seasonal: bool, horizon: int):
    """
    Forecast the `horizon` months after position `origin` of a monthly series,
    using ONLY data up to `origin`. Returns list of forecast values (len horizon).
    """
    win = monthly.iloc[origin - window_months + 1: origin + 1]
    days = sum(_days_in_month(d) for d in win.index)
    rate = float(win.sum()) / days
    idx12 = season_index(monthly, origin) if seasonal else None
    wmean = 1.0
    if idx12 is not None:
        wmean = float(np.mean(np.concatenate([[idx12[d.month - 1]] * _days_in_month(d) for d in win.index])))
        if not np.isfinite(wmean) or wmean <= 0:
            idx12, wmean = None, 1.0
    out = []
    last = monthly.index[origin]
    for k in range(1, horizon + 1):
        t = last + pd.DateOffset(months=k)
        f = 1.0 if idx12 is None else idx12[t.month - 1] / wmean
        out.append(rate * _days_in_month(t) * f)
    return out


def _backtest(monthly: pd.Series, window_months: int, seasonal: bool, horizon: int):
    """Replay the method from every past month-end that has `horizon` months of truth after it."""
    rows = []
    n = len(monthly)
    for o in range(window_months - 1, n - 1):
        if seasonal and season_index(monthly, o) is None:
            continue                                  # forecast would not be the same method
        fc = _forecast_from(monthly, o, window_months, seasonal, min(horizon, n - 1 - o))
        for k, f in enumerate(fc, start=1):
            rows.append({"k": k, "origin": monthly.index[o], "target": monthly.index[o + k],
                         "forecast": f, "actual": float(monthly.iloc[o + k])})
    return pd.DataFrame(rows)


def build_forecast(store: DataStore, f: Filters, p: Params, plan: Plan) -> dict:
    """Value chart: 12 months of actuals + 3 months forecast (with range) and department drilldown."""
    f_all, _ = _scope_frames(store, f)
    dem = apply(store.consumption, f_all, "Date")
    dem = dem[dem["Date"] <= plan.win_end]
    first_month = store.consumption["Date"].min()
    midx = _month_index(first_month, plan.win_end)
    monthly = _monthly(dem, "Value", midx)
    origin = len(midx) - 1

    series_hist = monthly.iloc[max(0, origin - P.HISTORY_MONTHS + 1):]
    out_pts = [{"month": d.strftime("%Y-%m"), "label": d.strftime("%b %Y"), "actual": _r(v, 0), "forecast": None,
                "low": None, "high": None} for d, v in series_hist.items()]

    result = {"points": out_pts, "accuracy_pct": None, "range_available": False, "season_used": False,
              "has_forecast": False}
    if origin + 1 < p.window_months or monthly.iloc[origin - p.window_months + 1:].sum() <= 0:
        return result

    fc = _forecast_from(monthly, origin, p.window_months, p.seasonality, P.FORECAST_MONTHS)
    result["season_used"] = bool(p.seasonality and season_index(monthly, origin) is not None)
    bt = _backtest(monthly, p.window_months, p.seasonality, P.FORECAST_MONTHS)
    band = {}
    if not bt.empty:
        bt = bt[bt["actual"] >= 0]
        for k, g in bt.groupby("k"):
            g = g[g["forecast"] > 0]
            if len(g) >= P.BACKTEST_MIN_SAMPLES:
                ratio = g["actual"] / g["forecast"]
                band[int(k)] = (float(ratio.quantile(P.BAND_LOW_Q)), float(ratio.quantile(P.BAND_HIGH_Q)))
        if len(bt) >= P.BACKTEST_MIN_SAMPLES and bt["actual"].sum() > 0:
            result["accuracy_pct"] = _r(100 * (1 - (bt["forecast"] - bt["actual"]).abs().sum() / bt["actual"].sum()), 1)
    result["range_available"] = bool(band)

    last = monthly.index[origin]
    for k, v in enumerate(fc, start=1):
        t = last + pd.DateOffset(months=k)
        lo, hi = band.get(k, (None, None))
        out_pts.append({"month": t.strftime("%Y-%m"), "label": t.strftime("%b %Y"), "actual": None,
                        "forecast": _r(v, 0),
                        "low": _r(v * lo, 0) if lo is not None else None,
                        "high": _r(v * hi, 0) if hi is not None else None})
    result["has_forecast"] = True
    result["forecast_total"] = _r(sum(fc), 0)
    result["_fc"] = fc
    result["_monthly"] = monthly
    return result


def _expected_demand(store: DataStore, f: Filters, p: Params, plan: Plan, fc_state: dict) -> tuple[float, float | None]:
    """Expected demand value for the next plan_days (honours Department) and change vs same dates last year."""
    f_all, _ = _scope_frames(store, f)
    dem = apply(store.consumption, f_all, "Date")
    dem = dem[dem["Date"] <= plan.win_end]
    w = dem[(dem["Date"] >= plan.win_start) & (dem["Date"] <= plan.win_end)]
    rate = float(w["Value"].sum()) / plan.window_days
    monthly = fc_state.get("_monthly")
    idx12 = season_index(monthly, len(monthly) - 1) if (p.seasonality and monthly is not None) else None
    first_day = plan.snapshot + pd.Timedelta(days=1)
    factors = _daily_factors(idx12, plan.win_start, plan.win_end, first_day, p.plan_days)
    expected = rate * float(factors.sum())
    ly_from = first_day - pd.DateOffset(years=1)
    ly_to = ly_from + pd.Timedelta(days=p.plan_days - 1)
    delta = None
    if ly_from >= pd.Timestamp(store.consumption["Date"].min()) and ly_to <= plan.win_end:
        ly = float(dem[(dem["Date"] >= ly_from) & (dem["Date"] <= ly_to)]["Value"].sum())
        if ly > 0:
            delta = (expected / ly - 1.0) * 100
    return expected, delta


# ----------------------------------------------------------------------------
# overview payload
# ----------------------------------------------------------------------------
def _line_row(r) -> dict:
    return {
        "item_id": r.Item_ID, "item_name": r.item_name, "unit_id": r.Unit_ID, "unit_name": r.unit_name,
        "group": r.group, "status": r.status,
        "on_hand": _r(r.on_hand, 0), "on_order": _r(r.on_order, 0),
        "daily_usage": _r(r.rate, 2), "cover_days": _r(r.cover_days, 1), "cover_capped": bool(r.cover_capped),
        "reorder_point": _r(r.reorder_point, 0), "order_qty": _r(r.order_qty, 0), "order_value": _r(r.order_value, 0),
        "order_in_days": _r(r.order_in_days, 1),
        "excess_qty": _r(r.excess_qty, 0), "excess_value": _r(r.excess_value, 0),
        "stock_value": _r(r.stock_value, 0),
    }


def status_rules(p: Params) -> dict[str, str]:
    """The exact rule behind each status, with this run's numbers filled in (mirrors _compute_plan)."""
    lt, bf, mc = p.lead_days, p.buffer_days, p.max_cover_days
    return {
        P.STATUS_CRITICAL: f"Needs an order (stock + on order is below the reorder point) and usable stock lasts less than the {lt}-day delivery time.",
        P.STATUS_ORDER_SOON: f"Needs an order (stock + on order is below the reorder point), but usable stock lasts at least {lt} days.",
        P.STATUS_HEALTHY: f"Stock + on order is above the reorder point (covers {lt}d delivery + {bf}d buffer) and usable stock is not above {mc} days of usage.",
        P.STATUS_EXCESS: f"No order needed, and usable stock is above {mc} days of usage.",
        P.STATUS_NO_USAGE: f"Usable stock on hand, but no usage in the last {p.window_months} months. All of it counts as excess value.",
        P.STATUS_NO_RECORD: f"Used in the last {p.window_months} months, but no inventory row on the snapshot date. Not planned (probably a data gap).",
    }


def _rows(df: pd.DataFrame, limit: int) -> tuple[list[dict], bool]:
    return [_line_row(r) for r in df.head(limit).itertuples(index=False)], len(df) > limit


def build_overview(store: DataStore, f: Filters, p: Params) -> dict:
    plan = compute_plan(store, f, p)
    fc = build_forecast(store, f, p, plan)
    L = plan.lines
    expected, delta = _expected_demand(store, f, p, plan, fc) if fc.get("has_forecast") else (0.0, None)

    order_df = L[(L["order_qty"] > 0)].sort_values(["status", "cover_days", "order_value"], ascending=[True, True, False],
                                                  key=lambda s: s.map({k: i for i, k in enumerate(P.STATUSES)}) if s.name == "status" else s)
    crit_df = L[L["status"] == P.STATUS_CRITICAL]
    exc_df = L[L["excess_qty"] > 0].sort_values("excess_value", ascending=False)
    exp_expired = float(plan.batches.loc[plan.batches["state"] == "expired", "risk_value"].sum()) if not plan.batches.empty else 0.0
    exp_soon = float(plan.batches.loc[plan.batches["state"] == "expiring", "risk_value"].sum()) if not plan.batches.empty else 0.0
    exc_val = float(exc_df["excess_value"].sum())

    kpis = [
        Kpi(label="Items to order now", value=float(len(order_df)), display=f"{len(order_df):,}", tone="risk" if len(order_df) else "positive",
            note=f"Worth {inr_compact(float(order_df['order_value'].sum()))} to order"),
        Kpi(label="Stock-out risk", value=float(len(crit_df)), display=f"{len(crit_df):,}", tone="risk" if len(crit_df) else "positive",
            note=f"Out of stock within {p.lead_days} days"),
        Kpi(label="Excess stock value", value=exc_val, display=inr_compact(exc_val), tone="risk" if exc_val > 0 else "positive",
            note=f"Above {p.max_cover_days} days of usage"),
        Kpi(label="Expiry at risk", value=exp_expired + exp_soon, display=inr_compact(exp_expired + exp_soon), tone="risk" if exp_expired + exp_soon > 0 else "positive",
            note=f"{inr_compact(exp_expired)} expired, {inr_compact(exp_soon)} expiring"),
        Kpi(label=f"Demand, next {p.plan_days} days", value=expected, display=inr_compact(expected),
            delta_pct=_r(delta, 1), tone="neutral",
            note="vs last year" + (" · department filter applied" if f.department != ALL else "")),
    ]

    # --- charts / tables ---------------------------------------------------------
    # Lowest on-hand cover first; among equals, the line least covered once open orders are counted.
    cover_df = (L[(L["rate"] > 0) & L["cover_days"].notna()]
                .sort_values(["cover_days", "position_cover_days"]).head(P.TOP_COVER_ROWS))
    cover = [{"label": f"{r.item_name} · {r.unit_name}", "item_id": r.Item_ID, "unit_id": r.Unit_ID,
              "cover_days": _r(r.cover_days, 1), "capped": bool(r.cover_capped), "status": r.status,
              "on_order": _r(r.on_order, 0)}
             for r in cover_df.itertuples(index=False)]

    health = []
    rules = status_rules(p)
    for s in P.STATUSES:
        g = L[L["status"] == s]
        health.append({"status": s, "lines": int(len(g)), "stock_value": _r(g["stock_value"].sum(), 0),
                       "help": P.STATUS_HELP[s], "rule": rules[s]})

    reorder, reorder_more = _rows(order_df, P.MAX_TABLE_ROWS)
    excess, excess_more = _rows(exc_df, P.MAX_TABLE_ROWS)

    insights = _insights(L, order_df, crit_df, exc_df, exp_expired + exp_soon, fc, p)
    notes = [
        f"Stock snapshot: {plan.snapshot:%d %b %Y}. Usage window: {plan.win_start:%d %b %Y} – {plan.win_end:%d %b %Y} ({plan.window_days} days).",
        plan.season_note,
        f"Delivery time ({p.lead_days}d) and safety buffer ({p.buffer_days}d) are assumptions (the data holds no vendor lead times); they are set in the backend configuration.",
        f"“On order” = purchase orders with status {P.OPEN_PO_STATUS}.",
        "The Period filter is not used: the plan is based on the latest stock snapshot. Expiry at risk can overlap with Excess stock.",
    ]
    n_gap = int((L["status"] == P.STATUS_NO_RECORD).sum())
    if n_gap:
        notes.append(f"{n_gap} item line(s) were used recently but have no stock record on {plan.snapshot:%d %b %Y}. "
                     "They are not planned (most likely a gap in the stock data, not a real stock-out).")
    if f.department != ALL:
        notes.append("Stock is not tracked by department, so reorder, excess and expiry cover the whole unit; only the demand forecast follows the Department filter.")

    return {
        "as_of": plan.snapshot.strftime("%Y-%m-%d"),
        "scope": f.scope_label(),
        "filters": f.as_dict(),
        "settings": p.as_dict(),
        "empty": plan.scope_empty,
        "department_note": f.department != ALL,
        "kpis": [k.model_dump() for k in kpis],
        "forecast": {k: v for k, v in fc.items() if not k.startswith("_")},
        "cover": {"rows": cover, "lead_days": p.lead_days},
        "health": health,
        "reorder": {"rows": reorder, "more": reorder_more, "total": int(len(order_df))},
        "excess": {"rows": excess, "more": excess_more, "total": int(len(exc_df))},
        "insights": insights,
        "notes": notes,
        "row_count": int(len(L)),
    }


def _insights(L, order_df, crit_df, exc_df, expiry_total, fc, p: Params) -> list[str]:
    out: list[str] = []
    if len(crit_df):
        top = crit_df.sort_values(["cover_days", "order_value"], ascending=[True, False]).iloc[0]
        out.append(f"Most urgent: {top['item_name']} at {top['unit_name']} - {top['cover_days']:.1f} days of cover left, "
                   f"{len(crit_df)} line(s) will run out within the {p.lead_days}-day delivery time.")
    if len(order_df):
        top = order_df.sort_values("order_value", ascending=False).iloc[0]
        out.append(f"Largest suggested order: {top['item_name']} at {top['unit_name']} "
                   f"({top['order_qty']:,.0f} units, {inr_compact(float(top['order_value']))}).")
    if len(exc_df):
        top = exc_df.iloc[0]
        out.append(f"Most money tied up in excess: {top['item_name']} at {top['unit_name']} "
                   f"({top['excess_qty']:,.0f} units, {inr_compact(float(top['excess_value']))}).")
    if not out:
        out.append("No stock-out or excess found for this selection.")
    return out


# ----------------------------------------------------------------------------
# one status (donut drill-down): every line behind a slice
# ----------------------------------------------------------------------------
def build_status(store: DataStore, f: Filters, p: Params, status: str) -> dict:
    if status not in P.STATUSES:
        raise PredictError(f"Unknown status '{status}'.")
    L = compute_plan(store, f, p).lines
    g = L[L["status"] == status]
    if status in (P.STATUS_CRITICAL, P.STATUS_ORDER_SOON):
        g = g.sort_values(["cover_days", "order_value"], ascending=[True, False])
    elif status == P.STATUS_EXCESS:
        g = g.sort_values("excess_value", ascending=False)
    elif status == P.STATUS_NO_RECORD:
        g = g.sort_values("rate", ascending=False)
    else:
        g = g.sort_values("stock_value", ascending=False)
    rows, more = _rows(g, P.MAX_TABLE_ROWS)
    return {
        "status": status, "help": P.STATUS_HELP[status], "rule": status_rules(p)[status],
        "total": int(len(g)), "more": more, "rows": rows,
        "stock_value": _r(g["stock_value"].sum(), 0),
        "order_value": _r(g["order_value"].sum(), 0),
        "excess_value": _r(g["excess_value"].sum(), 0),
    }


# ----------------------------------------------------------------------------
# one item (drill-down)
# ----------------------------------------------------------------------------
def build_item(store: DataStore, f: Filters, p: Params, item_id: str, unit_id: str) -> dict:
    plan = compute_plan(store, f, p)
    L = plan.lines
    row = L[(L["Item_ID"] == item_id) & (L["Unit_ID"] == unit_id)]
    if row.empty:
        raise PredictError("No stock, usage or open order for this item at this unit in the current selection.")
    r = row.iloc[0]
    rate, on_hand, on_order = float(r["rate"]), float(r["on_hand"]), float(r["on_order"])
    position = on_hand + on_order

    # projection: stock after expected usage; open orders land after the delivery time
    span_base = r["cover_days"] if pd.notna(r["cover_days"]) else 0.0
    span = int(np.clip(np.ceil(span_base) + p.lead_days + p.buffer_days, P.PROJECTION_MIN_DAYS, P.PROJECTION_MAX_DAYS))
    days = np.arange(0, span + 1)
    used = rate * _at(plan.cum, days)
    arrived = np.where(days >= p.lead_days, on_order, 0.0)
    stock_line = np.maximum(0.0, on_hand + arrived - used)
    rop_line = rate * (_at(plan.cum, days + p.lead_days + p.buffer_days) - _at(plan.cum, days))
    proj = [{"day": int(d), "date": (plan.snapshot + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d"),
             "stock": _r(s, 0), "reorder_point": _r(rp, 0)} for d, s, rp in zip(days, stock_line, rop_line)]

    # monthly quantity history + 3 month forecast for this item
    cons = _plan_consumption(store, replace(f, date_from=DATA_START, date_to=DATA_END, department=ALL))
    cons = cons[(cons["Item_ID"] == item_id) & (cons["Unit_ID"] == unit_id) & (cons["Date"] <= plan.win_end)]
    midx = _month_index(store.consumption["Date"].min(), plan.win_end)
    monthly = _monthly(cons, "Qty", midx)
    hist = monthly.iloc[max(0, len(midx) - P.HISTORY_MONTHS):]
    pts = [{"label": d.strftime("%b %Y"), "actual": _r(v, 0), "forecast": None} for d, v in hist.items()]
    if rate > 0:
        first_day = plan.snapshot + pd.Timedelta(days=1)
        for k in range(1, P.FORECAST_MONTHS + 1):
            t = plan.win_end + pd.DateOffset(months=k)
            t0 = t.to_period("M").to_timestamp()
            n = _days_in_month(t0)
            off = int((t0 - first_day).days)
            m = rate * float(_at(plan.cum, off + n) - _at(plan.cum, off))
            pts.append({"label": t0.strftime("%b %Y"), "actual": None, "forecast": _r(m, 0)})

    b = plan.batches[(plan.batches["Item_ID"] == item_id) & (plan.batches["Unit_ID"] == unit_id)].sort_values("days_to_expiry")
    batches = [{"batch": str(x.Batch_No), "expiry": x.Expiry_Date.strftime("%Y-%m-%d") if pd.notna(x.Expiry_Date) else None,
                "days_to_expiry": int(x.days_to_expiry), "qty": _r(x.qty, 0), "expected_used": _r(x.used_qty, 0),
                "at_risk_qty": _r(x.risk_qty, 0), "at_risk_value": _r(x.risk_value, 0), "state": x.state}
               for x in b.itertuples(index=False)]

    order_in = r["order_in_days"]
    # A date is only meaningful when the order is due within the "maximum cover" span; beyond that it is just noise.
    soon = not pd.isna(order_in) and order_in <= p.max_cover_days
    order_by = None if not soon else (plan.snapshot + pd.Timedelta(days=int(np.floor(order_in)))).strftime("%Y-%m-%d")
    return {
        "item_id": item_id, "item_name": r["item_name"], "unit_id": unit_id, "unit_name": r["unit_name"], "group": r["group"],
        "status": r["status"], "status_help": P.STATUS_HELP[r["status"]],
        "as_of": plan.snapshot.strftime("%Y-%m-%d"),
        "settings": p.as_dict(),
        "facts": {
            "expired_qty": _r(r["expired_qty"], 0),
            "on_hand": _r(on_hand, 0), "on_order": _r(on_order, 0), "position": _r(position, 0),
            "daily_usage": _r(rate, 2), "cover_days": _r(r["cover_days"], 1), "cover_capped": bool(r["cover_capped"]),
            "reorder_point": _r(r["reorder_point"], 0), "order_up_to": _r(r["order_up_to"], 0),
            "order_qty": _r(r["order_qty"], 0), "order_value": _r(r["order_value"], 0), "unit_price": _r(r["unit_price"], 2),
            "order_in_days": _r(order_in, 1), "order_by": order_by,
            "excess_qty": _r(r["excess_qty"], 0), "excess_value": _r(r["excess_value"], 0),
        },
        "history": pts,
        "projection": proj,
        "batches": batches,
        "explain": _explain(r, p, order_by),
        "notes": [plan.season_note, f"Open orders are assumed to arrive after the {p.lead_days}-day delivery time."],
    }


def _explain(r, p: Params, order_by: str | None = None) -> list[str]:
    """Plain-language walk-through of this row's numbers, built from the same values."""
    rate = float(r["rate"])
    out = [f"Daily usage: {rate:.2f} units/day (average of the last {p.window_months} months)." if rate > 0 else "No usage in the chosen window."]
    if r["status"] == P.STATUS_NO_RECORD:
        return out + ["There is no stock record for this item on the snapshot date, so it is not planned."]
    if r["expired_qty"] > 0:
        out.append(f"{r['expired_qty']:,.0f} units on the shelf are expired and are not counted as usable stock.")
    if rate > 0:
        cap = "more than " if r["cover_capped"] else ""
        out.append(f"Usable stock {r['on_hand']:,.0f} will last about {cap}{r['cover_days']:.1f} days at the expected usage "
                   f"(busy and quiet months are taken into account).")
        out.append(f"Reorder point {r['reorder_point']:,.0f} = usage during the {p.lead_days}-day delivery + {p.buffer_days}-day buffer. "
                   f"Below it, an order is needed.")
        side = "below" if r["position"] < r["reorder_point"] else "not below"
        out.append(f"Stock + on order = {r['on_hand']:,.0f} + {r['on_order']:,.0f} = {r['position']:,.0f}, which is {side} the reorder point"
                   f"{' - so an order is needed.' if r['order_qty'] > 0 else ' - so no order is needed now.'}")
        if r["order_qty"] > 0:
            out.append(f"Order-up-to level {r['order_up_to']:,.0f} = usage over delivery + buffer + {p.plan_days} days. "
                       f"Order {r['order_up_to']:,.0f} - {r['position']:,.0f} = {r['order_qty']:,.0f} units.")
        elif order_by:
            out.append(f"Stock + on order is expected to fall to the reorder point around {pd.Timestamp(order_by):%d %b %Y}; order by then.")
    return out
