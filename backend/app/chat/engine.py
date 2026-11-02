"""
The deterministic executor: ResolvedQuery -> ResultSet.

Every figure the chatbot reports is computed here, with pandas, from the same
DataStore frames the dashboards use. The model never touches a number.

Correctness rules this module enforces:
  * Stock (snapshot) measures are never summed across snapshot dates. Without
    a time grouping the latest snapshot in the period is used ("as on"); with
    one, the last snapshot inside each bucket.
  * Ratios are computed from summed numerator and denominator per group - never
    by averaging percentages. Division by zero is "no value", not 0.
  * Budget is planned by whole months, so budget queries use whole months.
  * The 'Total' is evaluated on its own (not by adding rows) so it is right for
    ratios and distinct counts too.
  * Groups are ranked by an independent evaluation, so "top 5 per month" ranks
    on the whole period, not per bucket.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import product
from typing import Optional

import numpy as np
import pandas as pd

from app import metrics as dashboard_metrics        # the dashboards' own arithmetic
from app.chat import semantic as sem
from app.chat.catalog import Catalog
from app.chat.resolver import ResolvedFilter, ResolvedQuery, is_additive
from app.chat.timeparse import (Period, add_months, bucket_label, bucket_starts,
                                fmt_range, month_start, previous_period)

log = logging.getLogger("manipal.chat")

_NONE = "\x00none"          # stand-in for missing group values (pandas groupby drops NaN keys)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class ResultSet:
    query: ResolvedQuery
    df: pd.DataFrame                    # dim label columns, _period, measure columns, extras
    group_dims: list
    grain: str
    totals: dict                        # measure id -> overall value (None if undefined)
    prior_totals: Optional[dict] = None
    prior_period: Optional[Period] = None
    notes: list = field(default_factory=list)
    snapshot_dates: dict = field(default_factory=dict)   # table -> [Timestamp]
    rows_used: int = 0
    empty: bool = False
    empty_reason: str = ""
    truncated: bool = False             # table rows were capped

    @property
    def measure_ids(self) -> list:
        return [m.id for m in self.query.measures]


# ---------------------------------------------------------------------------
# Evaluator: one set of keys (group dims + optional time bucket), many measures
# ---------------------------------------------------------------------------
class Evaluator:
    def __init__(self, store, cat: Catalog, filters: list, group_dims: list,
                 grain: str, period: Period):
        self.store, self.cat = store, cat
        self.filters = filters
        self.group_dims = list(group_dims)
        self.grain = grain
        self.period = period
        self.keys = self.group_dims + (["__bucket"] if grain != "none" else [])
        self.notes: list[str] = []
        self.snapshot_dates: dict = {}
        self.rows_used: dict = {}
        self._cache: dict = {}

    # ---- frames -----------------------------------------------------------
    def _dim_mask(self, df: pd.DataFrame, table_id: str, f: ResolvedFilter) -> pd.Series:
        col = sem.DIMENSIONS[f.dim_id].columns[table_id]
        s = df[col]
        non_null = [v for v in f.raw_values if v is not None]
        m = s.isin(non_null)
        if None in f.raw_values:
            m = m | s.isna()
        return m if f.op == "in" else ~m

    def _filtered(self, table_id: str, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
        """Rows with date in [lo, hi] that satisfy the dimension filters."""
        t = sem.TABLES[table_id]
        df = getattr(self.store, t.attr)
        dc = df[t.date_col]
        df = df[(dc >= lo) & (dc <= hi)]
        for f in self.filters:
            if table_id in sem.DIMENSIONS[f.dim_id].columns:
                df = df[self._dim_mask(df, table_id, f)]
        return df

    def _frame(self, table_id: str) -> pd.DataFrame:
        if table_id in self._cache:
            return self._cache[table_id]
        t = sem.TABLES[table_id]
        lo, hi = pd.Timestamp(self.period.start), pd.Timestamp(self.period.end)
        fiscal = self.cat.fiscal

        if t.kind == "snapshot":
            dates = list(self.cat.tables[table_id].snapshot_dates)
            in_range = [d for d in dates if lo <= d <= hi]
            if self.grain == "none":
                if in_range:
                    chosen = [max(in_range)]
                    if len(in_range) > 1:
                        self.notes.append(
                            f"Stock is a point-in-time figure, so it is shown as on "
                            f"{chosen[0]:%d %b %Y} (the latest snapshot in the period), "
                            f"not summed across months.")
                else:
                    before = [d for d in dates if d <= hi]
                    chosen = [max(before)] if before else []
                    if chosen:
                        self.notes.append(
                            f"No stock snapshot falls inside the period (snapshots are month-end); "
                            f"showing the latest one on or before it: {chosen[0]:%d %b %Y}.")
            else:
                if in_range:
                    s = pd.Series(in_range)
                    b = bucket_starts(s, self.grain, fiscal)
                    chosen = s.groupby(b.values).max().tolist()
                else:
                    chosen = []
            self.snapshot_dates[table_id] = chosen
            df = getattr(self.store, t.attr)
            df = df[df[t.date_col].isin(chosen)]
            for f in self.filters:
                if table_id in sem.DIMENSIONS[f.dim_id].columns:
                    df = df[self._dim_mask(df, table_id, f)]
        else:
            df = self._filtered(table_id, lo, hi)

        if self.grain != "none":
            df = df.assign(__bucket=bucket_starts(df[t.date_col], self.grain, fiscal)
                           if len(df) else pd.Series(dtype="datetime64[ns]"))
        self._cache[table_id] = df
        return df

    # ---- grouping helpers ----------------------------------------------------
    def _keyed(self, df: pd.DataFrame, table_id: str) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for d in self.group_dims:
            s = df[sem.DIMENSIONS[d].columns[table_id]]
            out[d] = s.astype(object).where(s.notna(), _NONE)
        if self.grain != "none":
            out["__bucket"] = df["__bucket"]
        if not self.keys:
            out["__all__"] = 1
        return out

    @property
    def _key_cols(self) -> list:
        return self.keys if self.keys else ["__all__"]

    # ---- cond / agg --------------------------------------------------------
    def _cond_mask(self, df: pd.DataFrame, c: sem.Cond) -> pd.Series:
        v = c.value
        if isinstance(v, sem.Ref):
            v = sem.resolve_ref(v, self.store)
        s = df[c.column]
        if c.op == "eq":
            return s == v
        if c.op == "ne":
            return s != v
        vals = list(v) if isinstance(v, (list, tuple, set)) else [v]
        m = s.isin(vals)
        return m if c.op == "in" else ~m

    def _agg(self, a: sem.Agg) -> pd.Series:
        df = self._frame(a.table)
        for c in a.where:
            df = df[self._cond_mask(df, c)]
        self.rows_used[a.table] = max(self.rows_used.get(a.table, 0), len(df))
        keyed = self._keyed(df, a.table)
        if a.op != "count":
            keyed["__v"] = df[a.column].to_numpy()
        g = keyed.groupby(self._key_cols, sort=False, dropna=False)
        if a.op == "sum":
            s = g["__v"].sum()
        elif a.op == "count":
            s = g.size()
        elif a.op == "nunique":
            s = g["__v"].nunique()
        elif a.op == "mean":
            s = g["__v"].mean()
        else:                                           # pragma: no cover (validated at startup)
            raise ValueError(f"bad agg op {a.op}")
        s.index = s.index.set_names(self._key_cols)
        return s.astype("float64")

    # ---- inventory days ----------------------------------------------------
    def _empty_series(self) -> pd.Series:
        names = self._key_cols
        idx = (pd.MultiIndex.from_arrays([[] for _ in names], names=names)
               if len(names) > 1 else pd.Index([], name=names[0]))
        return pd.Series([], index=idx, dtype="float64")

    def _inventory_days(self, e: sem.InventoryDays) -> pd.Series:
        """
        Client definition, evaluated per stock snapshot date:
            stock value x day-of-month / consumption month-to-date
        The arithmetic is metrics.inventory_days - the dashboards' own function.
        Consumption MTD always runs from the 1st of the snapshot's month, even
        if the requested period starts mid-month.
        """
        inv = self._frame(e.stock.table)
        snaps = sorted(self.snapshot_dates.get(e.stock.table, []))
        if inv.empty or not snaps:
            return self._empty_series()
        ct = e.consumption.table
        cons = self._filtered(ct, pd.Timestamp(month_start(snaps[0].date())), snaps[-1])
        dc_inv = sem.TABLES[e.stock.table].date_col
        dc_con = sem.TABLES[ct].date_col
        dim_keys = self.group_dims or ["__all__"]

        def grouped(df: pd.DataFrame, table_id: str, col: str) -> pd.Series:
            k = pd.DataFrame(index=df.index)
            for d in self.group_dims:
                s = df[sem.DIMENSIONS[d].columns[table_id]]
                k[d] = s.astype(object).where(s.notna(), _NONE)
            if not self.group_dims:
                k["__all__"] = 1
            k["__v"] = df[col].to_numpy()
            return k.groupby(dim_keys, sort=False, dropna=False)["__v"].sum()

        tuples, values = [], []
        for d in snaps:
            stock = grouped(inv[inv[dc_inv] == d], e.stock.table, e.stock.column)
            mtd_df = cons[(cons[dc_con] >= pd.Timestamp(month_start(d.date()))) & (cons[dc_con] <= d)]
            mtd = grouped(mtd_df, ct, e.consumption.column) if len(mtd_df) else None
            bucket = (bucket_starts(pd.Series([d]), self.grain, self.cat.fiscal).iloc[0]
                      if self.grain != "none" else None)
            for key, sv in stock.items():
                mv = float(mtd.get(key, 0.0)) if mtd is not None else 0.0
                values.append(dashboard_metrics.inventory_days(float(sv), mv, d.day) if mv else np.nan)
                # With no group-by dimensions the dummy "__all__" key must not leak into the
                # index when a time bucket supplies the only key column (monthly trend).
                kt = (key if isinstance(key, tuple) else (key,)) if (self.group_dims or bucket is None) else ()
                tuples.append(kt + ((bucket,) if bucket is not None else ()))
        names = self._key_cols
        idx = (pd.MultiIndex.from_tuples(tuples, names=names) if len(names) > 1
               else pd.Index([t[0] for t in tuples], name=names[0]))
        return pd.Series(values, index=idx, dtype="float64")

    # ---- expression evaluation ----------------------------------------------
    def compute(self, measures: list) -> pd.DataFrame:
        """DataFrame indexed by self.keys, one column per measure id."""
        raw: dict = {}
        for m in measures:
            if isinstance(m.expr, sem.InventoryDays):
                raw[m.expr] = self._inventory_days(m.expr)
            else:
                for a in sem.expr_aggs(m.expr):
                    if a not in raw:
                        raw[a] = self._agg(a)

        nonempty = [s.index for s in raw.values() if len(s)]
        if not nonempty:
            return pd.DataFrame(columns=[m.id for m in measures])
        union = nonempty[0]
        for i in nonempty[1:]:
            union = union.union(i, sort=False)

        def aligned(key, s):
            zero_fill = isinstance(key, sem.Agg) and key.op != "mean"
            return s.reindex(union, fill_value=0.0) if zero_fill else s.reindex(union)

        al = {k: aligned(k, s) for k, s in raw.items()}

        def ev(e) -> pd.Series:
            if isinstance(e, (sem.Agg, sem.InventoryDays)):
                return al[e]
            l, r = ev(e.left), ev(e.right)
            if e.op == "sub":
                out = l - r
            elif e.op == "div":
                out = l / r.where(r != 0)
            else:                                           # pragma: no cover
                raise ValueError(f"bad op {e.op}")
            return out * e.scale if e.scale != 1.0 else out

        out = pd.DataFrame({m.id: ev(m.expr) for m in measures}, index=union)
        out.index = out.index.set_names(self._key_cols)
        return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _fill_zero(m: sem.Measure) -> bool:
    """Measures where "no rows" genuinely means 0 (sums/counts, not ratios)."""
    def f(e):
        if isinstance(e, sem.Agg):
            return e.op in ("sum", "count", "nunique")
        if isinstance(e, sem.BinOp):
            return e.op == "sub" and f(e.left) and f(e.right)
        return False
    return f(m.expr)


def _label_of(info, raw) -> str:
    if raw == _NONE:
        raw = None
    return info.raw_to_label.get(raw, str(raw))


def execute(store, cat: Catalog, q: ResolvedQuery, max_table_rows: int) -> ResultSet:
    ev = Evaluator(store, cat, q.filters, q.group_dims, q.grain, q.period)
    main = ev.compute(q.measures)
    notes = list(q.notes) + ev.notes

    # ---- totals (own evaluation: right for ratios and distinct counts) --------
    tot_ev = Evaluator(store, cat, q.filters, [], "none", q.period)
    tot_df = tot_ev.compute(q.measures)
    totals = {m.id: (None if tot_df.empty or pd.isna(tot_df[m.id].iloc[0])
                     else float(tot_df[m.id].iloc[0])) for m in q.measures}
    for n in tot_ev.notes:
        if n not in notes:
            notes.append(n)

    rows_used = sum(ev.rows_used.values()) if ev.rows_used else 0
    if main.empty:
        return ResultSet(q, pd.DataFrame(), q.group_dims, q.grain, totals, notes=_dedupe(notes),
                         snapshot_dates=ev.snapshot_dates, rows_used=rows_used, empty=True,
                         empty_reason=_diagnose_empty(store, cat, q))

    # ---- densify a time series so every bucket appears (sums -> 0) --------------
    if q.grain != "none":
        months = pd.date_range(pd.Timestamp(q.period.start).replace(day=1),
                               pd.Timestamp(q.period.end), freq="MS")
        buckets = sorted(set(bucket_starts(pd.Series(months), q.grain, cat.fiscal)))
        if q.group_dims:
            groups = list(dict.fromkeys(main.index.droplevel("__bucket")))
            full = pd.MultiIndex.from_tuples(
                [((g if isinstance(g, tuple) else (g,)) + (b,)) for g in groups for b in buckets],
                names=main.index.names)
        else:
            full = pd.Index(buckets, name="__bucket")
        main = main.reindex(full)
        for m in q.measures:
            if _fill_zero(m):
                main[m.id] = main[m.id].fillna(0.0)

    # ---- rank groups on the whole period -------------------------------------
    rank_order: list = []
    if q.group_dims:
        d0 = q.group_dims[0]
        if q.grain != "none" or len(q.group_dims) > 1:
            r_ev = Evaluator(store, cat, q.filters, [d0], "none", q.period)
            r_df = r_ev.compute([m for m in q.measures if m.id == q.sort_by])
            rk = r_df[q.sort_by] if not r_df.empty else pd.Series(dtype=float)
        else:
            rk = main[q.sort_by]
        rk = rk.sort_values(ascending=not q.sort_desc, na_position="last", kind="stable")
        rank_order = list(rk.index)

    flat = main.reset_index()
    if not q.group_dims and q.grain == "none":
        flat = flat.drop(columns=["__all__"], errors="ignore")

    # ---- keep only top-N groups ------------------------------------------------
    if q.limit and q.group_dims:
        keep = set(rank_order[:q.limit])
        flat = flat[flat[q.group_dims[0]].isin(keep)]

    # ---- natural order for ordered dimensions (tiers, ageing) when not ranked ----
    d0_info = cat.dim(q.group_dims[0]) if q.group_dims else None
    natural = (q.group_dims and q.spec.sort_by is None and len(q.group_dims) == 1
               and q.grain == "none" and d0_info.dim.order is not None)

    # ---- readable labels -------------------------------------------------------
    raw_d0 = flat[q.group_dims[0]].copy() if q.group_dims else None
    for d in q.group_dims:
        info = cat.dim(d)
        flat[d] = flat[d].map(lambda r, info=info: _label_of(info, r))
    if q.grain != "none":
        flat["_period_start"] = flat["__bucket"]
        flat["_period"] = flat["__bucket"].map(lambda t: bucket_label(t, q.grain, cat.fiscal))
        flat = flat.drop(columns=["__bucket"])
        notes.extend(_partial_bucket_notes(flat, q, cat))

    # ---- ordering ------------------------------------------------------------------
    if q.group_dims:
        if natural:
            pos = {l: i for i, l in enumerate(d0_info.ordered_labels)}
            flat["_o0"] = flat[q.group_dims[0]].map(lambda l: pos.get(l, 10_000))
        else:
            pos = {_label_of(d0_info, r): i for i, r in enumerate(rank_order)}
            flat["_o0"] = flat[q.group_dims[0]].map(lambda l: pos.get(l, 10_000))
        sort_cols = (["_period_start"] if q.grain != "none" else []) + ["_o0"]
        if len(q.group_dims) > 1:
            sort_cols.append(q.sort_by)
            asc = [True] * (len(sort_cols) - 1) + [not q.sort_desc]
        else:
            asc = [True] * len(sort_cols)
        flat = flat.sort_values(sort_cols, ascending=asc, kind="stable", na_position="last")
        flat = flat.drop(columns=["_o0"])
    elif q.grain != "none":
        flat = flat.sort_values("_period_start", kind="stable")
    flat = flat.reset_index(drop=True)

    # ---- share of total (additive measures) ------------------------------------------
    if q.show_share:
        for m in q.measures:
            if is_additive(m):
                grp = flat.groupby("_period_start")[m.id].transform("sum") if q.grain != "none" \
                    else flat[m.id].sum()
                flat[f"{m.id}__share"] = np.where(grp != 0, flat[m.id] / grp * 100, np.nan)

    # ---- comparison with the previous period / previous bucket --------------------------
    prior_totals = prior_period = None
    if q.compare_previous:
        if q.grain != "none":
            for m in q.measures:
                grp = flat.groupby(q.group_dims, sort=False)[m.id] if q.group_dims else flat[m.id]
                if m.unit in ("percent", "days"):
                    flat[f"{m.id}__chg"] = grp.diff()
                else:
                    prev = grp.shift(1)
                    flat[f"{m.id}__chg"] = np.where(prev.fillna(0) != 0,
                                                    (flat[m.id] - prev) / prev * 100, np.nan)
        else:
            pp = previous_period(q.period)
            if pp.end < cat.data_start:
                notes.append("No comparison period: there is no data before the selected period.")
            else:
                if pp.start < cat.data_start:
                    notes.append(f"The previous period is only partly covered by the data "
                                 f"({fmt_range(max(pp.start, cat.data_start), pp.end)}).")
                prior_period = pp
                p_ev = Evaluator(store, cat, q.filters, q.group_dims, "none", pp)
                p_df = p_ev.compute(q.measures)
                pt_ev = Evaluator(store, cat, q.filters, [], "none", pp)
                pt = pt_ev.compute(q.measures)
                prior_totals = {m.id: (None if pt.empty or pd.isna(pt[m.id].iloc[0])
                                       else float(pt[m.id].iloc[0])) for m in q.measures}
                if q.group_dims and not p_df.empty:
                    pf = p_df.reset_index()
                    for d in q.group_dims:
                        info = cat.dim(d)
                        pf[d] = pf[d].map(lambda r, info=info: _label_of(info, r))
                    pf = pf.set_index(q.group_dims)
                    for m in q.measures:
                        flat[f"{m.id}__prior"] = flat.set_index(q.group_dims).index.map(
                            lambda k: pf[m.id].get(k, np.nan)).to_numpy()
                        _delta_cols(flat, m)

    truncated = False
    if len(flat) > max_table_rows:
        flat = flat.head(max_table_rows)
        truncated = True
        notes.append(f"Showing the first {max_table_rows} rows.")

    return ResultSet(q, flat, q.group_dims, q.grain, totals, prior_totals, prior_period,
                     _dedupe(notes), ev.snapshot_dates, rows_used, truncated=truncated)


def _bucket_end(start: pd.Timestamp, grain: str) -> pd.Timestamp:
    months = {"month": 1, "quarter": 3, "fiscal_year": 12, "year": 12}[grain]
    return pd.Timestamp(add_months(start.date(), months)) - pd.Timedelta(days=1)


def _partial_bucket_notes(flat: pd.DataFrame, q: ResolvedQuery, cat: Catalog) -> list:
    """Flag buckets (e.g. FY2025) that the period or the data only partly covers,
    so a part-year is never read as a full year."""
    out = []
    lo, hi = pd.Timestamp(q.period.start), pd.Timestamp(q.period.end)
    for start, label in dict.fromkeys(zip(flat["_period_start"], flat["_period"])):
        end = _bucket_end(start, q.grain)
        if start < lo or end > hi:
            cs, ce = max(start, lo), min(end, hi)
            out.append(f"{label} is a partial period in this view: only "
                       f"{fmt_range(cs.date(), ce.date())} is included.")
    return out


def _delta_cols(flat: pd.DataFrame, m: sem.Measure) -> None:
    prior = flat[f"{m.id}__prior"]
    flat[f"{m.id}__delta"] = flat[m.id] - prior
    if m.unit not in ("percent", "days"):
        flat[f"{m.id}__delta_pct"] = np.where(prior.fillna(0) != 0,
                                              (flat[m.id] - prior) / prior * 100, np.nan)


def _dedupe(items: list) -> list:
    return list(dict.fromkeys(items))


def _diagnose_empty(store, cat: Catalog, q: ResolvedQuery) -> str:
    """Say WHY nothing came back (which filter or period removed the data)."""
    lo, hi = pd.Timestamp(q.period.start), pd.Timestamp(q.period.end)
    for tid in sorted(q.tables):
        t = sem.TABLES[tid]
        if t.kind == "snapshot":
            continue
        ev = Evaluator(store, cat, [], [], "none", q.period)
        if ev._filtered(tid, lo, hi).empty:
            return f"There are no {t.label.lower()} records in {q.period.label}."
        for f in q.filters:
            if tid not in sem.DIMENSIONS[f.dim_id].columns:
                continue
            ev1 = Evaluator(store, cat, [f], [], "none", q.period)
            if ev1._filtered(tid, lo, hi).empty:
                return (f"There are no {t.label.lower()} records for "
                        f"{', '.join(f.labels)} in {q.period.label}.")
    return "No records match all of those conditions together."
