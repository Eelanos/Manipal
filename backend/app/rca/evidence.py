"""
"Is this unusual?" - the only statistics the RCA uses.

For a quantity (a ratio's level, or an additive measure's change/gap) we take
its value in every OTHER month, and report how many standard deviations the
selected month sits from that history. Nothing is fitted or forecast; the
verdict is just "compared with its own past".

  ratio measures  (compliance %, non-moving %...) -> the LEVEL in each month
  additive measures (consumption, inventory days)  -> the CHANGE in each month
                                                      versus the same comparison
                                                      (prior month / last year / budget)

Levels of additive measures are not used because they trend and have seasons,
which would make almost every December look "unusual".
"""

from __future__ import annotations

import math

import pandas as pd

from app.config import RCA_MIN_HISTORY_MONTHS, RCA_Z_UNUSUAL, RCA_Z_WATCH


def _monthly(s: pd.Series) -> pd.Series:
    if s is None or s.empty:
        return pd.Series(dtype=float)
    idx = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    return s.astype(float).reindex(idx)


def quantity(kind: str, series: pd.Series, compare_key: str,
             budget_series: pd.Series | None = None) -> tuple[pd.Series | None, str]:
    """The series whose history we compare the selected month against, plus a plain-words basis."""
    s = _monthly(series)
    if kind == "ratio":
        return s, "level"
    if compare_key == "prior_month":
        return s.diff(1), "month-on-month change"
    if compare_key == "same_month_last_year":
        return s - s.shift(12), "year-on-year change"
    if compare_key == "budget":
        if budget_series is None:
            return None, "gap to budget"
        return s - _monthly(budget_series).reindex(s.index), "gap to budget"
    return None, "n/a"


def _clean(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def verdict(q: pd.Series | None, focus: pd.Timestamp, basis: str, with_history: bool = True) -> dict:
    if q is None or focus not in q.index or pd.isna(q.loc[focus]):
        return {"available": False, "reason": "Not enough data to compare this month with its history.",
                "basis": basis}
    hist = q.drop(focus).dropna()
    n = int(len(hist))
    if n < RCA_MIN_HISTORY_MONTHS:
        return {"available": False, "basis": basis,
                "reason": f"Only {n} comparable months of history; at least {RCA_MIN_HISTORY_MONTHS} are needed."}
    sd = float(hist.std(ddof=1))
    if not math.isfinite(sd) or sd == 0:
        return {"available": False, "basis": basis, "reason": "History is flat, so a deviation cannot be measured."}
    mean = float(hist.mean())
    x = float(q.loc[focus])
    z = (x - mean) / sd
    flag = "unusual" if abs(z) >= RCA_Z_UNUSUAL else "watch" if abs(z) >= RCA_Z_WATCH else "normal"
    out = {"available": True, "basis": basis, "value": x, "z": z, "n": n, "mean": mean, "sd": sd, "flag": flag}
    if with_history:
        out["history"] = [{"month": d.strftime("%Y-%m"), "value": _clean(v)}
                          for d, v in q.dropna().items()]
        out["focus_month"] = focus.strftime("%Y-%m")
    return out
