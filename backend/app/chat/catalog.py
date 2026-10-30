"""
The live catalog: everything the chatbot knows about THIS dataset, discovered
from the DataStore at startup rather than typed in.

  * which values each dimension really has (units, departments, doctors ...)
  * how each value may be spelled by a user (labels + aliases)
  * date coverage per table, and the stock snapshot dates
  * the fiscal calendar (start month and FY labelling), derived from the data's
    own FY / FY_Month columns - so there is no hardcoded "April"

If the data changes (new units, new departments, a longer date range), the
catalog changes with it; no code edits needed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from app import config as cfg
from app.chat import semantic as sem

log = logging.getLogger("manipal.chat")

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_text(s: Any) -> str:
    """'Dr. Meera  Shah' / 'molecule_4' -> 'dr meera shah' / 'molecule 4'."""
    return _NON_ALNUM.sub(" ", str(s).lower()).strip()


@dataclass
class DimInfo:
    dim: sem.Dimension
    raw_to_label: dict          # raw value (incl. None) -> display label
    label_to_raw: dict          # display label -> raw
    alias_to_raw: dict          # normalized alias/label -> set of raw values
    ordered_labels: list        # labels in natural order

    @property
    def n_values(self) -> int:
        return len(self.raw_to_label)


@dataclass
class TableInfo:
    table: sem.TableDef
    rows: int
    date_min: pd.Timestamp
    date_max: pd.Timestamp
    snapshot_dates: list = field(default_factory=list)


@dataclass
class FiscalCalendar:
    start_month: int            # 1-12, first month of the fiscal year
    label_offset: int           # FY label = calendar year of start + label_offset

    def fy_of(self, d: date) -> int:
        start_year = d.year if d.month >= self.start_month else d.year - 1
        return start_year + self.label_offset

    def fy_start_year(self, fy: int) -> int:
        return fy - self.label_offset


@dataclass
class Catalog:
    dims: dict
    tables: dict
    fiscal: FiscalCalendar
    data_start: date
    data_end: date
    as_of: date
    problems: list

    def dim(self, dim_id: str) -> DimInfo:
        return self.dims[dim_id]


def _ordered(info_labels: dict, order: Any) -> list:
    labels = list(info_labels.values())
    if order:
        pos = {info_labels.get(r, str(r)): i for i, r in enumerate(order)}
        labels.sort(key=lambda l: (pos.get(l, 10_000), l))
    else:
        labels.sort(key=lambda l: str(l).lower())
    return labels


def _derive_fiscal(store) -> FiscalCalendar:
    """
    Fiscal start month = calendar month in which FY_Month == 1.
    FY label offset = FY - calendar-year-of-FY-start (1 means 'FY2026 ends in 2026').
    Both read off the consumption table's own FY / FY_Month columns.
    """
    c = store.consumption
    first = c[c["FY_Month"] == 1]
    if first.empty:
        raise ValueError("Cannot derive fiscal calendar: no FY_Month == 1 rows")
    start_month = int(first["Date"].dt.month.mode().iloc[0])
    sample = c[c["Date"].dt.month >= start_month].iloc[0]
    offset = int(sample["FY"]) - int(sample["Date"].year)
    return FiscalCalendar(start_month=start_month, label_offset=offset)


def build_catalog(store) -> Catalog:
    problems = sem.validate_registry(store)

    tables: dict = {}
    for t in sem.TABLES.values():
        df = getattr(store, t.attr)
        dc = df[t.date_col]
        info = TableInfo(t, len(df), dc.min(), dc.max())
        if t.kind == "snapshot":
            info.snapshot_dates = sorted(pd.to_datetime(dc.unique()))
        tables[t.id] = info

    dims: dict = {}
    for d in sem.DIMENSIONS.values():
        raw_values: set = set()
        for tid, col in d.columns.items():
            if tid not in tables:
                continue
            series = getattr(store, sem.TABLES[tid].attr)[col]
            for v in series.dropna().unique():
                raw_values.add(bool(v) if isinstance(v, (bool, np.bool_)) else v)
            if series.isna().any():
                raw_values.add(None)

        label_map = d.value_labels(store) if callable(d.value_labels) else (d.value_labels or {})
        raw_to_label = {}
        for r in raw_values:
            if r is None:
                raw_to_label[None] = d.null_label or "(none)"
            else:
                raw_to_label[r] = label_map.get(r, str(r))
        label_to_raw = {l: r for r, l in raw_to_label.items()}

        alias_to_raw: dict = {}

        def add(alias: Any, raw: Any):
            key = normalize_text(alias)
            if key:
                alias_to_raw.setdefault(key, set()).add(raw)

        extra = d.aliases(store) if d.aliases else {}
        for raw, label in raw_to_label.items():
            add(label, raw)
            if raw is not None and not isinstance(raw, bool):
                add(raw, raw)
            for a in extra.get(raw, []):
                add(a, raw)

        order = d.order(store) if callable(d.order) else d.order
        dims[d.id] = DimInfo(d, raw_to_label, label_to_raw, alias_to_raw,
                             _ordered(raw_to_label, order))

    cat = Catalog(
        dims=dims, tables=tables, fiscal=_derive_fiscal(store),
        data_start=cfg.DATA_START, data_end=cfg.DATA_END,
        as_of=cfg.AS_OF_DATE, problems=problems,
    )
    for p in problems:
        log.warning("semantic registry problem: %s", p)
    return cat


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    from app.data_loader import get_store
    return build_catalog(get_store())
