"""
Time handling. The model never does date arithmetic: it emits a SYMBOLIC
period ("the fiscal year before this one", "the last 6 months", "Mar 2026")
and this module turns it into exact dates.

Two rules inherited from the dashboards (see app/config.py):
  1. "Today" is config.AS_OF_DATE, never datetime.now(). The data runs to
     31 Dec 2026, so relative words must be anchored there or a live demo
     would ask for months that have no data.
  2. The fiscal calendar comes from the data itself (catalog.FiscalCalendar).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from app.chat.catalog import Catalog, FiscalCalendar


class PlanError(ValueError):
    """A plan the engine cannot honour. The message is shown to the user or
    fed back to the planner, so it must be specific and actionable."""

    def __init__(self, message: str, suggestions: Optional[list] = None):
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions or []


MONTH_ABBR = [calendar.month_abbr[i] for i in range(13)]  # [''] + Jan..Dec


@dataclass(frozen=True)
class Period:
    start: date
    end: date                      # inclusive
    label: str
    notes: tuple = ()
    unit: Optional[str] = None     # set for "a whole fiscal year / quarter / month ..." requests

    @property
    def whole_months(self) -> bool:
        return self.start.day == 1 and self.end.day == calendar.monthrange(
            self.end.year, self.end.month)[1]


# ---------------------------------------------------------------------------
# Calendar arithmetic
# ---------------------------------------------------------------------------
def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    """First day of the month `n` months after d's month."""
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def _shift_for(unit: str, month: int, fiscal: FiscalCalendar) -> int:
    """Months between the start of d's `unit`-period and d's own month start."""
    if unit == "month":
        return 0
    if unit == "quarter":
        return ((month - fiscal.start_month) % 12) % 3
    if unit == "fiscal_year":
        return (month - fiscal.start_month) % 12
    if unit == "year":
        return month - 1
    raise PlanError(f"Unknown period unit '{unit}'.")


_UNIT_MONTHS = {"month": 1, "quarter": 3, "fiscal_year": 12, "year": 12}


def period_bounds(unit: str, anchor: date, fiscal: FiscalCalendar) -> tuple[date, date]:
    start = add_months(anchor, -_shift_for(unit, anchor.month, fiscal))
    end = month_end(add_months(start, _UNIT_MONTHS[unit] - 1))
    return start, end


def fmt_range(start: date, end: date) -> str:
    def ym(d: date) -> str:
        return f"{MONTH_ABBR[d.month]} {d.year}"
    whole = start.day == 1 and end.day == calendar.monthrange(end.year, end.month)[1]
    if whole:
        return ym(start) if (start.year, start.month) == (end.year, end.month) \
            else f"{ym(start)} – {ym(end)}"
    return f"{start.day} {ym(start)} – {end.day} {ym(end)}"


def describe(unit: str, start: date, end: date, fiscal: FiscalCalendar) -> str:
    if unit == "fiscal_year":
        return f"FY{fiscal.fy_of(start)} ({fmt_range(start, end)})"
    if unit == "quarter":
        q = ((start.month - fiscal.start_month) % 12) // 3 + 1
        return f"FY{str(fiscal.fy_of(start))[-2:]} Q{q} ({fmt_range(start, end)})"
    if unit == "year":
        return f"{start.year}"
    return fmt_range(start, end)


# ---------------------------------------------------------------------------
# Resolving a TimeSpec
# ---------------------------------------------------------------------------
def _parse_iso(s: Optional[str], what: str) -> date:
    if not s:
        raise PlanError(f"The period needs a {what} date.")
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        raise PlanError(f"'{s}' is not a valid date; use YYYY-MM-DD.")


def resolve_period(ts, cat: Catalog) -> Period:
    """
    ts: a TimeSpec-like object (kind, unit, count, fiscal_year, calendar_year,
    month, quarter, start_date, end_date). Returns the exact Period, clipped
    to the data's coverage, with notes explaining anything adjusted.
    """
    fiscal, as_of = cat.fiscal, cat.as_of
    kind = ts.kind
    notes: list[str] = []
    unit_hint: Optional[str] = None

    if kind == "all":
        start, end = cat.data_start, cat.data_end
        label = f"Full range ({fmt_range(start, end)})"

    elif kind in ("relative", "trailing"):
        if ts.unit is None:
            raise PlanError("A relative period needs a unit (month, quarter, fiscal_year or year).")
        n = ts.count if ts.count is not None else (0 if kind == "relative" else 1)
        if n < 0 or n > 120:
            raise PlanError("Period count must be between 0 and 120.")
        cur_s, cur_e = period_bounds(ts.unit, as_of, fiscal)
        if kind == "relative":
            unit_hint = ts.unit
            start = add_months(cur_s, -n * _UNIT_MONTHS[ts.unit])
            end = month_end(add_months(start, _UNIT_MONTHS[ts.unit] - 1))
            label = describe(ts.unit, start, end, fiscal)
            if n == 0 and as_of < end:
                # The current period is still in progress: say so, and show the dates actually covered.
                end = as_of
                label = describe(ts.unit, start, end, fiscal).replace(" (", " to date (", 1)
        else:
            if n < 1:
                raise PlanError("A trailing period needs a count of at least 1.")
            start = add_months(cur_s, -(n - 1) * _UNIT_MONTHS[ts.unit])
            end = min(cur_e, as_of)
            label = f"Last {n} {ts.unit.replace('_', ' ')}{'s' if n > 1 else ''} ({fmt_range(start, end)})"

    elif kind == "fiscal_year":
        if ts.fiscal_year is None:
            raise PlanError("A fiscal-year period needs the fiscal year, e.g. 2026 for FY2026.")
        fy = _normalise_year(ts.fiscal_year)
        start = date(fiscal.fy_start_year(fy), fiscal.start_month, 1)
        end = month_end(add_months(start, 11))
        label = describe("fiscal_year", start, end, fiscal)
        unit_hint = "fiscal_year"

    elif kind == "calendar_year":
        if ts.calendar_year is None:
            raise PlanError("A calendar-year period needs the year.")
        y = _normalise_year(ts.calendar_year)
        start, end = date(y, 1, 1), date(y, 12, 31)
        label = f"Calendar {y}"
        unit_hint = "year"

    elif kind == "month":
        if ts.calendar_year is None or ts.month is None:
            raise PlanError("A month period needs both the year and the month number.")
        if not 1 <= ts.month <= 12:
            raise PlanError("Month must be 1-12.")
        start = date(_normalise_year(ts.calendar_year), ts.month, 1)
        end = month_end(start)
        label = fmt_range(start, end)
        unit_hint = "month"

    elif kind == "fiscal_quarter":
        if ts.fiscal_year is None or ts.quarter is None:
            raise PlanError("A fiscal-quarter period needs the fiscal year and quarter (1-4).")
        if not 1 <= ts.quarter <= 4:
            raise PlanError("Quarter must be 1-4.")
        fy = _normalise_year(ts.fiscal_year)
        start = add_months(date(fiscal.fy_start_year(fy), fiscal.start_month, 1), 3 * (ts.quarter - 1))
        end = month_end(add_months(start, 2))
        label = describe("quarter", start, end, fiscal)
        unit_hint = "quarter"

    elif kind == "between":
        start = _parse_iso(ts.start_date, "start")
        end = _parse_iso(ts.end_date, "end")
        if end < start:
            raise PlanError("The period's end date is before its start date.")
        label = fmt_range(start, end)

    else:
        raise PlanError(f"Unknown period kind '{kind}'.")

    # Clip to what the data covers, and say so - silently returning a shorter
    # window than the user asked for would misstate the answer.
    if end < cat.data_start or start > cat.data_end:
        raise PlanError(
            f"There is no data for {label}. The data covers "
            f"{fmt_range(cat.data_start, cat.data_end)}.")
    c_start, c_end = max(start, cat.data_start), min(end, cat.data_end)
    if (c_start, c_end) != (start, end):
        notes.append(
            f"Requested {label}; the data covers {fmt_range(cat.data_start, cat.data_end)}, "
            f"so showing {fmt_range(c_start, c_end)}.")
        label = fmt_range(c_start, c_end)
    return Period(c_start, c_end, label, tuple(notes), unit_hint)


def _normalise_year(y: int) -> int:
    """Accept 26 as 2026 (people write FY26)."""
    return 2000 + y if 0 <= y < 100 else y


def expand_to_whole_months(p: Period) -> Period:
    """Monthly-grain tables (budget) cannot be compared on part-months."""
    if p.whole_months:
        return p
    s, e = month_start(p.start), month_end(p.end)
    return Period(s, e, fmt_range(s, e),
                  p.notes + (f"Budget is planned by whole months, so the period was widened to {fmt_range(s, e)}.",),
                  p.unit)


def previous_period(p: Period) -> Period:
    """
    The window to compare against.
      * A named period (a fiscal year, quarter or month) is compared with the
        SAME months one unit earlier - so a part-year (FY2027 to date) is set
        against the same part of the previous year, like for like.
      * Anything else (trailing windows, custom ranges, whole dataset) is
        compared with the equally long window immediately before it.
    """
    if p.unit:
        k = _UNIT_MONTHS[p.unit]
        start = add_months(p.start, -k)
        end = month_end(add_months(month_start(p.end), -k))
        return Period(start, end, fmt_range(start, end), (), p.unit)
    if p.whole_months:
        n = (p.end.year * 12 + p.end.month) - (p.start.year * 12 + p.start.month) + 1
        start = add_months(p.start, -n)
        end = p.start - timedelta(days=1)
        return Period(start, end, fmt_range(start, end))
    span = (p.end - p.start).days + 1
    end = p.start - timedelta(days=1)
    start = end - timedelta(days=span - 1)
    return Period(start, end, fmt_range(start, end))


# ---------------------------------------------------------------------------
# Time buckets for "by month / quarter / year" groupings
# ---------------------------------------------------------------------------
def bucket_starts(dates: pd.Series, grain: str, fiscal: FiscalCalendar) -> pd.Series:
    """Start-of-bucket timestamp for every date (vectorised)."""
    d = pd.to_datetime(dates)
    months = d.values.astype("datetime64[M]")
    if grain == "month":
        shift = np.zeros(len(d), dtype="int64")
    else:
        month = d.dt.month.to_numpy()
        if grain == "quarter":
            shift = ((month - fiscal.start_month) % 12) % 3
        elif grain == "fiscal_year":
            shift = (month - fiscal.start_month) % 12
        elif grain == "year":
            shift = month - 1
        else:
            raise PlanError(f"Unknown time grain '{grain}'.")
    start = months - shift.astype("timedelta64[M]")
    return pd.Series(pd.DatetimeIndex(start.astype("datetime64[ns]")), index=d.index)


def bucket_label(ts: pd.Timestamp, grain: str, fiscal: FiscalCalendar) -> str:
    d = ts.date()
    if grain == "month":
        return f"{MONTH_ABBR[d.month]} {str(d.year)[-2:]}"          # "Mar 26", as on the dashboards
    if grain == "quarter":
        q = ((d.month - fiscal.start_month) % 12) // 3 + 1
        return f"FY{str(fiscal.fy_of(d))[-2:]} Q{q}"
    if grain == "fiscal_year":
        return f"FY{fiscal.fy_of(d)}"
    if grain == "year":
        return str(d.year)
    raise PlanError(f"Unknown time grain '{grain}'.")
