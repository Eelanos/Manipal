"""
The measures RCA can explain, and the exact arithmetic that splits a change in
each one across segments.

THE RULE: every split here is an identity, not an estimate. For any measure,
the contributions of all segments (plus the few named non-segment effects)
add up EXACTLY to the change being explained. The engine checks this on every
request and reports the result, so a number on screen can always be traced.

How each form is split (m = the month explained, b = the comparison):

  SUM  (Consumption value)
      change = X(m) - X(b)                      -> segment: X_s(m) - X_s(b)

  SHARE  (Formulary compliance, Non-moving %, Near-expiry & expired %)
      value  = A + sign * 100 * N / D           (N = the "bad" amount, D = the total)
      change = sign * 100 * (N(m)/D(m) - N(b)/D(b))
                                                -> segment: sign*100*(N_s(m)/D(m) - N_s(b)/D(b))
      Each segment is measured against the SAME totals, so the segments add up
      to the change in the whole. Versus a target T the segment is
      100*((1-T)*D_s - N_s)/D: its off-target amount over what the target allows.

  DAYS  (Inventory Days = Stock x days-in-month / Consumption, as on the
         Inventory dashboard; see metrics.inventory_days)
      change = S1*D1/C1 - S0*D0/C0
             = (S1-S0)*D1/C1                    stock effect
             - days0*(C1-C0)/C1                 consumption effect
             + S0*(D1-D0)/C1                    calendar effect (different month lengths)
      Stock and consumption effects are split per segment; the calendar effect
      is its own bar because a month's length is not a segment.
      Versus budget: days_act - days_bud = -days_act*(C-B)/B, split per segment.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from app.config import DATA_END, DATA_START, FORMULARY_TARGET_PCT, RCA_STOCK_CLASS_ORDER
from app.filters import ALL, Filters, apply
from app.rca.dims import DIMS, dim_in_data, has_dim, seg_series

TOTAL = "__total__"

# The budget table is set per unit and department, and carries the unit's region and zone, so a
# budget comparison can be split by exactly these.
BUDGET_DIMS = ("unit", "department", "region", "zone")
BUDGET_DIMS_TEXT = "unit, department, region and zone"


class RcaError(ValueError):
    """A problem the user can act on (bad month, comparison unavailable...)."""


@dataclass(frozen=True)
class Base:
    kind: str                       # "month" | "budget" | "target"
    key: str                        # prior_month | same_month_last_year | budget | target
    label: str
    month: pd.Timestamp | None = None


# --------------------------------------------------------------------------
# Scope: the data the analysis may look at
# --------------------------------------------------------------------------
class Scope:
    """
    `*_full` = every row in the user's scope (top-bar Unit / Stock Take Group /
    Department). Totals and denominators always come from here.
    `*_sl`   = the same rows narrowed by the drill path (e.g. Unit = PUN).
    Segments are counted from the slice but measured against the full totals, so
    a drill step always explains a part of the ORIGINAL change.
    """

    def __init__(self, store, f: Filters, conds: list[tuple[str, str]]):
        f_all = replace(f, date_from=DATA_START, date_to=DATA_END)
        self.cons_full = apply(store.consumption, f_all, "Date")
        self.inv_full = apply(store.inventory, f_all, "Date")
        self.bud_full = apply(store.budget, f_all, "Date")
        self.stg_filtered = f.stock_take_group != ALL
        self._set_conds(conds)

    def _set_conds(self, conds: list[tuple[str, str]]) -> None:
        self.conds = list(conds)
        self.cons_sl = _cut(self.cons_full, conds)
        self.inv_sl = _cut(self.inv_full, conds)
        self.bud_reason: str | None = None
        if self.stg_filtered:
            self.bud_reason = "Budget is set per unit and department, not per stock take group."
        elif any(d not in BUDGET_DIMS for d, _ in conds):
            self.bud_reason = f"Budget is only available by {BUDGET_DIMS_TEXT}."
        self.bud_sl = _cut(self.bud_full, conds)

    def with_conds(self, conds: list[tuple[str, str]]) -> "Scope":
        other = copy.copy(self)
        other._set_conds(conds)
        return other


def _cut(df: pd.DataFrame, conds: list[tuple[str, str]]) -> pd.DataFrame:
    for dim, val in conds:
        if not has_dim(df, dim):
            return df.iloc[0:0]
        df = df[seg_series(df, dim) == val]
    return df


# --------------------------------------------------------------------------
# Small aggregation helpers
# --------------------------------------------------------------------------
def long(df: pd.DataFrame, dim: str | None, spec: dict) -> pd.DataFrame:
    """One row per (month, segment) with the named sums. spec = {name: (column, mask_fn|None)}."""
    cols = ["m", "seg", *spec]
    if df is None or not len(df):
        return pd.DataFrame({c: pd.Series(dtype=float if c not in ("m", "seg") else object) for c in cols})
    ms = df["Month_Start"]
    out = pd.DataFrame({
        # Month_Start is already a datetime column; re-parsing it on every call was the slowest part.
        "m": (ms if pd.api.types.is_datetime64_any_dtype(ms) else pd.to_datetime(ms)).to_numpy(),
        "seg": seg_series(df, dim).to_numpy() if dim else TOTAL,
    })
    for name, (col, mask) in spec.items():
        v = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        if mask is not None:
            v = np.where(np.asarray(mask(df), dtype=bool), v, 0.0)
        out[name] = v
    return out.groupby(["m", "seg"], as_index=False)[list(spec)].sum()


def at(lg: pd.DataFrame, month: pd.Timestamp) -> pd.DataFrame:
    return lg[lg["m"] == month].set_index("seg").drop(columns="m")


def total(lg: pd.DataFrame, month: pd.Timestamp, name: str) -> float:
    return float(lg.loc[lg["m"] == month, name].sum())


def align(*frames: pd.DataFrame) -> list[pd.DataFrame]:
    idx = frames[0].index
    for fr in frames[1:]:
        idx = idx.union(fr.index)
    return [fr.reindex(idx, fill_value=0.0) for fr in frames]


def _div(a, b):
    """Elementwise a/b with NaN (not inf) where b is not positive."""
    b = pd.Series(b, dtype=float) if not isinstance(b, pd.Series) else b
    return a / b.where(b > 0)


@dataclass
class Contribs:
    frame: pd.DataFrame                      # index = segment
    effects: list[dict] = field(default_factory=list)   # non-segment effects
    base_value: float | None = None

    @property
    def slice_total(self) -> float:
        return float(self.frame["contribution"].sum())


# --------------------------------------------------------------------------
# Measures
# --------------------------------------------------------------------------
class Measure:
    key = ""
    label = ""
    fmt = "number"                  # currency | percent | days
    unit_word = ""                  # "pp" for percent, "days" for days, "" for currency
    higher_is = "neutral"           # better | worse | neutral
    kind = "sum"                    # sum | ratio | days
    definition = ""
    dims: tuple[str, ...] = ()
    compares: tuple[str, ...] = ("prior_month", "same_month_last_year")
    target: float | None = None
    weight_label = ""

    # -- implemented by subclasses
    def root_value(self, sc: Scope, m) -> float | None: raise NotImplementedError
    def root_series(self, sc: Scope) -> pd.Series: raise NotImplementedError
    def root_budget_series(self, sc: Scope) -> pd.Series | None: return None
    def seg_series(self, sc: Scope, dim: str) -> pd.DataFrame: raise NotImplementedError
    def seg_budget_series(self, sc: Scope, dim: str) -> pd.DataFrame | None: return None
    def contributions(self, sc: Scope, dim: str | None, m, base: Base) -> Contribs: raise NotImplementedError

    def base_value(self, sc: Scope, m, base: Base) -> float | None:
        if base.kind == "month":
            return self.root_value(sc, base.month)
        if base.kind == "target":
            return self.target
        if base.kind == "budget":
            s = self.root_budget_series(sc)
            return None if s is None or m not in s.index else float(s.loc[m])
        raise RcaError(f"Unknown comparison {base.kind}")

    def has_data(self, sc: Scope, m) -> bool:
        return self.root_value(sc, m) is not None

    def frames_for(self, sc: Scope) -> list[pd.DataFrame]:
        """The (full-scope) tables this measure is calculated from."""
        return [sc.cons_full]

    def seg_count(self, sc: Scope, dim: str) -> int:
        """How many distinct values of `dim` exist in this measure's data in the user's scope."""
        labels: set[str] = set()
        for df in self.frames_for(sc):
            if has_dim(df, dim) and len(df):
                labels |= set(seg_series(df, dim).unique())
        return len(labels)

    def dims_for(self, base_key: str) -> list[str]:
        ds = [d for d in self.dims if d in BUDGET_DIMS] if base_key == "budget" else list(self.dims)
        return [d for d in ds if dim_in_data(d)]


# ---- SUM ------------------------------------------------------------------
class ConsumptionValue(Measure):
    key = "consumption"
    label = "Consumption value"
    fmt = "currency"
    kind = "sum"
    higher_is = "neutral"
    definition = "Total value of items consumed in the month (Consumption dashboard)."
    dims = ("region", "zone", "unit", "department", "item", "doctor", "payer", "patient_type", "episode",
            "package", "store", "category", "tier", "stock_group", "implant", "essential")
    compares = ("prior_month", "same_month_last_year", "budget")
    weight_label = "Share of consumption"
    _cons = {"X": ("Value", None)}
    _bud = {"X": ("Budget_Value", None)}

    def root_series(self, sc):
        lg = long(sc.cons_full, None, self._cons)
        return lg.set_index("m")["X"].sort_index()

    def root_value(self, sc, m):
        lg = long(sc.cons_full, None, self._cons)
        return total(lg, m, "X") if (lg["m"] == m).any() else None

    def root_budget_series(self, sc):
        if sc.bud_reason or not len(sc.bud_full):
            return None
        return long(sc.bud_full, None, self._bud).set_index("m")["X"].sort_index()

    def seg_series(self, sc, dim):
        lg = long(sc.cons_sl, dim, self._cons)
        return lg.pivot(index="m", columns="seg", values="X").sort_index()

    def seg_budget_series(self, sc, dim):
        if sc.bud_reason or dim not in BUDGET_DIMS:
            return None
        lg = long(sc.bud_sl, dim, self._bud)
        return lg.pivot(index="m", columns="seg", values="X").sort_index()

    def contributions(self, sc, dim, m, base):
        lg = long(sc.cons_sl, dim, self._cons)
        cur = at(lg, m)
        if base.kind == "month":
            b = at(lg, base.month)
        elif base.kind == "budget":
            if sc.bud_reason:
                raise RcaError(sc.bud_reason)
            b = at(long(sc.bud_sl, dim, self._bud), m)
        else:
            raise RcaError("Consumption has no target to compare against.")
        cur, b = align(cur, b)
        tot_cur = total(long(sc.cons_full, None, self._cons), m, "X")
        fr = pd.DataFrame({
            "contribution": cur["X"] - b["X"],
            "own_current": cur["X"],
            "own_base": b["X"],
            "weight": 100 * _div(cur["X"], pd.Series(tot_cur, index=cur.index)),
        })
        return Contribs(fr)


# ---- SHARE ----------------------------------------------------------------
class ShareMeasure(Measure):
    kind = "ratio"
    fmt = "percent"
    unit_word = "pp"

    def __init__(self, *, key, label, definition, table, den_col, num_mask, sign, offset,
                 higher_is, dims, compares, target=None, weight_label=""):
        self.key, self.label, self.definition = key, label, definition
        self.table, self.den_col, self.num_mask = table, den_col, num_mask
        self.sign, self.offset, self.higher_is = sign, offset, higher_is
        self.dims, self.compares, self.target = dims, compares, target
        self.weight_label = weight_label
        self._spec = {"D": (den_col, None), "N": (den_col, num_mask)}

    def frames_for(self, sc): return [self._full(sc)]

    def _full(self, sc): return sc.cons_full if self.table == "cons" else sc.inv_full
    def _sl(self, sc): return sc.cons_sl if self.table == "cons" else sc.inv_sl

    def own(self, lg: pd.DataFrame) -> pd.Series:
        return self.offset + self.sign * 100 * _div(lg["N"], lg["D"])

    def root_series(self, sc):
        lg = long(self._full(sc), None, self._spec)
        lg = lg[lg["D"] > 0]
        return pd.Series(self.own(lg).to_numpy(), index=pd.DatetimeIndex(lg["m"])).sort_index()

    def root_value(self, sc, m):
        lg = long(self._full(sc), None, self._spec)
        row = lg[lg["m"] == m]
        if not len(row) or float(row["D"].sum()) <= 0:
            return None
        return float(self.own(row).iloc[0])

    def seg_series(self, sc, dim):
        lg = long(self._sl(sc), dim, self._spec)
        lg = lg.assign(v=self.own(lg))
        return lg.pivot(index="m", columns="seg", values="v").sort_index()

    def contributions(self, sc, dim, m, base):
        lg = long(self._sl(sc), dim, self._spec)
        tot_lg = long(self._full(sc), None, self._spec)
        cur = at(lg, m)
        d_cur = total(tot_lg, m, "D")
        if d_cur <= 0:
            raise RcaError("No data for the selected month in this scope.")
        if base.kind == "month":
            b = at(lg, base.month)
            d_base = total(tot_lg, base.month, "D")
            if d_base <= 0:
                raise RcaError(f"No data for {base.label} in this scope.")
            cur, b = align(cur, b)
            contrib = self.sign * 100 * (cur["N"] / d_cur - b["N"] / d_base)
            own_base = self.own(b)
        elif base.kind == "target":
            if self.target is None or not (self.sign == -1 and self.offset == 100):
                raise RcaError(f"{self.label} has no target to compare against.")
            cur, = align(cur)
            t = self.target / 100.0
            # What each segment's bad amount is, over what the target would allow it.
            contrib = 100 * ((1 - t) * cur["D"] - cur["N"]) / d_cur
            own_base = pd.Series(self.target, index=cur.index)
        else:
            raise RcaError(f"{self.label} cannot be compared with {base.label}.")
        fr = pd.DataFrame({
            "contribution": contrib,
            "own_current": self.own(cur),
            "own_base": own_base,
            "weight": 100 * cur["D"] / d_cur,
        })
        return Contribs(fr)


# ---- DAYS -----------------------------------------------------------------
class InventoryDays(Measure):
    key = "inventory_days"
    label = "Inventory days"
    fmt = "days"
    unit_word = "days"
    kind = "days"
    higher_is = "neutral"
    definition = ("Stock value x days in the month / consumption in the month, using the month-end stock "
                  "(the formula on the Inventory Analysis dashboard).")
    dims = ("region", "zone", "unit", "department", "item", "stock_group", "store", "category", "tier",
            "implant", "essential")
    compares = ("prior_month", "same_month_last_year", "budget")
    weight_label = "Share of stock"
    _inv = {"S": ("Stock_Value", None)}
    _cons = {"C": ("Value", None)}
    _bud = {"B": ("Budget_Value", None)}

    def frames_for(self, sc):
        return [sc.inv_full, sc.cons_full]

    @staticmethod
    def _days(S, C, D):
        return S * D / C.where(C > 0)

    def _series(self, inv, cons):
        s = long(inv, None, self._inv).set_index("m")["S"]
        c = long(cons, None, self._cons).set_index("m")["C"]
        idx = s.index.intersection(c.index)
        s, c = s.loc[idx], c.loc[idx]
        d = pd.Series(pd.DatetimeIndex(idx).days_in_month, index=idx, dtype=float)
        return self._days(s, c, d).dropna().sort_index()

    def root_series(self, sc):
        return self._series(sc.inv_full, sc.cons_full)

    def root_value(self, sc, m):
        s = self.root_series(sc)
        return float(s.loc[m]) if m in s.index else None

    def root_budget_series(self, sc):
        if sc.bud_reason or not len(sc.bud_full):
            return None
        s = long(sc.inv_full, None, self._inv).set_index("m")["S"]
        b = long(sc.bud_full, None, self._bud).set_index("m")["B"]
        idx = s.index.intersection(b.index)
        d = pd.Series(pd.DatetimeIndex(idx).days_in_month, index=idx, dtype=float)
        return self._days(s.loc[idx], b.loc[idx], d).dropna().sort_index()

    def _wide(self, inv, cons, dim):
        s = long(inv, dim, self._inv).pivot(index="m", columns="seg", values="S")
        c = long(cons, dim, self._cons).pivot(index="m", columns="seg", values="C")
        cols = s.columns.union(c.columns)
        idx = s.index.union(c.index)
        s, c = s.reindex(index=idx, columns=cols).fillna(0.0), c.reindex(index=idx, columns=cols).fillna(0.0)
        return s, c

    def seg_series(self, sc, dim):
        s, c = self._wide(sc.inv_sl, sc.cons_sl, dim)
        d = pd.Series(pd.DatetimeIndex(s.index).days_in_month, index=s.index, dtype=float)
        out = s.mul(d, axis=0) / c.where(c > 0)
        return out.sort_index()

    def seg_budget_series(self, sc, dim):
        if sc.bud_reason or dim not in BUDGET_DIMS:
            return None
        s = long(sc.inv_sl, dim, self._inv).pivot(index="m", columns="seg", values="S")
        b = long(sc.bud_sl, dim, self._bud).pivot(index="m", columns="seg", values="B")
        cols = s.columns.intersection(b.columns)
        idx = s.index.intersection(b.index)
        s, b = s.loc[idx, cols], b.loc[idx, cols]
        d = pd.Series(pd.DatetimeIndex(idx).days_in_month, index=idx, dtype=float)
        return (s.mul(d, axis=0) / b.where(b > 0)).sort_index()

    def contributions(self, sc, dim, m, base):
        inv_t = long(sc.inv_full, None, self._inv)
        con_t = long(sc.cons_full, None, self._cons)
        S1, C1 = total(inv_t, m, "S"), total(con_t, m, "C")
        D1 = float(m.days_in_month)
        if S1 <= 0 or C1 <= 0:
            raise RcaError("No stock or consumption data for the selected month in this scope.")
        s_lg = long(sc.inv_sl, dim, self._inv)
        c_lg = long(sc.cons_sl, dim, self._cons)
        s1, c1 = at(s_lg, m), at(c_lg, m)
        effects: list[dict] = []
        if base.kind == "month":
            S0, C0 = total(inv_t, base.month, "S"), total(con_t, base.month, "C")
            D0 = float(base.month.days_in_month)
            if S0 <= 0 or C0 <= 0:
                raise RcaError(f"No stock or consumption data for {base.label} in this scope.")
            days0 = S0 * D0 / C0
            s0, c0 = at(s_lg, base.month), at(c_lg, base.month)
            s1, s0, c1, c0 = align(s1.rename(columns={"S": "S"}), s0, c1, c0)
            stock_eff = (s1["S"] - s0["S"]) * D1 / C1
            cons_eff = -days0 * (c1["C"] - c0["C"]) / C1
            fr = pd.DataFrame({
                "contribution": stock_eff + cons_eff,
                "stock_effect": stock_eff,
                "consumption_effect": cons_eff,
                "own_current": self._days(s1["S"], c1["C"], D1),
                "own_base": self._days(s0["S"], c0["C"], D0),
                "weight": 100 * s1["S"] / S1,
            })
            if D1 != D0:
                effects.append({"label": "Days in month (calendar)",
                                "contribution": S0 * (D1 - D0) / C1})
        elif base.kind == "budget":
            if sc.bud_reason:
                raise RcaError(sc.bud_reason)
            b_t = long(sc.bud_full, None, self._bud)
            B1 = total(b_t, m, "B")
            if B1 <= 0:
                raise RcaError("No budget for the selected month in this scope.")
            days_act = S1 * D1 / C1
            b1 = at(long(sc.bud_sl, dim, self._bud), m)
            s1, c1, b1 = align(s1, c1, b1)
            cons_eff = -days_act * (c1["C"] - b1["B"]) / B1
            fr = pd.DataFrame({
                "contribution": cons_eff,
                "consumption_effect": cons_eff,
                "own_current": self._days(s1["S"], c1["C"], D1),
                "own_base": self._days(s1["S"], b1["B"], D1),
                "weight": 100 * s1["S"] / S1,
            })
        else:
            raise RcaError("Inventory days has no target to compare against.")
        return Contribs(fr, effects)


# ---- registry -------------------------------------------------------------
_INV_DIMS = ("region", "zone", "unit", "department", "item", "stock_group", "store", "category", "tier",
             "implant", "essential")
_CONS_DIMS = ConsumptionValue.dims

MEASURES: dict[str, Measure] = {m.key: m for m in [
    ShareMeasure(
        key="formulary_compliance", label="Formulary compliance",
        definition=("Share of consumption value that is on-formulary (the Formulary Compliance dashboard). "
                    "Contributions are percentage points (pp) of compliance."),
        table="cons", den_col="Value", num_mask=lambda df: ~(df["Is_Formulary"] == True),  # noqa: E712
        # Formulary tier is left out: "off-formulary" IS the OOF tier, so splitting by it
        # would just restate the metric (a 100% "driver" that says nothing).
        sign=-1, offset=100, higher_is="better", dims=tuple(d for d in _CONS_DIMS if d != "tier"),
        compares=("prior_month", "same_month_last_year", "target"),
        target=FORMULARY_TARGET_PCT, weight_label="Share of consumption"),
    ConsumptionValue(),
    InventoryDays(),
    ShareMeasure(
        key="non_moving_pct", label="Non-moving stock %",
        definition=("Share of month-end stock value flagged Non Moving (no issue in 90 days). "
                    "Contributions are percentage points (pp)."),
        table="inv", den_col="Stock_Value", num_mask=lambda df: df["Moving/Non Moving"] == "Non Moving",
        sign=1, offset=0, higher_is="worse", dims=_INV_DIMS,
        compares=("prior_month", "same_month_last_year"), weight_label="Share of stock"),
    ShareMeasure(
        key="expiry_risk_pct", label="Near-expiry & expired stock %",
        definition=("Share of month-end stock value that is Near Expiry (within 90 days) or already Expired. "
                    "Contributions are percentage points (pp)."),
        table="inv", den_col="Stock_Value",
        num_mask=lambda df: df["Expiry/Near Expiry"].isin(["Near Expiry", "Expired"]),
        sign=1, offset=0, higher_is="worse", dims=_INV_DIMS,
        compares=("prior_month", "same_month_last_year"), weight_label="Share of stock"),
]}

COMPARE_LABELS = {
    "prior_month": "Prior month",
    "same_month_last_year": "Same month last year",
    "budget": "Budget",
    "target": "Target",
}


def stock_class(inv: pd.DataFrame) -> pd.Series:
    """Each stock line in exactly one class (first match in RCA_STOCK_CLASS_ORDER)."""
    exp = inv["Expiry/Near Expiry"]
    flags = {
        "Expired": exp == "Expired",
        "Near expiry": exp == "Near Expiry",
        "Non-moving": inv["Moving/Non Moving"] == "Non Moving",
        "Healthy": pd.Series(True, index=inv.index),
    }
    out = pd.Series(RCA_STOCK_CLASS_ORDER[-1], index=inv.index, dtype=object)
    assigned = pd.Series(False, index=inv.index)
    for name in RCA_STOCK_CLASS_ORDER:
        hit = flags[name] & ~assigned
        out[hit] = name
        assigned |= hit
    return out
