"""
Presentation: ResultSet -> the exact shapes the frontend already renders.

KPIs and charts reuse app.schemas.Kpi / Chart, so the dashboards' own
KpiCard and ChartPanel components draw them unchanged (same colours, same
Indian currency formatting, same hover behaviour). Tables get a small extra
envelope (totals row, truncation flag) defined here.

Chart choice is rule-based on the SHAPE of the result - the model only
supplies an optional hint, which is honoured only if it makes sense for the
data (a donut of percentages, say, would be refused).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.chat import semantic as sem
from app.chat.engine import ResultSet
from app.chat.resolver import is_additive
from app.formatting import inr_compact, inr_full, qty_compact
from app.schemas import Chart, ChartSeries, Kpi

MAX_CHART_SERIES = 8
MAX_STACK_GROUPS = 6       # above this, extra groups are folded into "All others" in stacked charts
PIVOT_MAX_GROUPS = 12
MAX_CHART_CATEGORIES = 15
DONUT_MAX_SLICES = 8

_FORMAT = {"currency": "currency", "percent": "percent", "number": "number", "days": "number"}


# ---------------------------------------------------------------------------
# Number formatting (single place; facts and KPI cards both use it)
# ---------------------------------------------------------------------------
def fmt_value(v: Optional[float], unit: str) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if unit == "currency":
        # Client convention is Crores; below 1 lakh a Crore figure rounds to
        # 0.00, so show exact rupees there instead of a useless "₹0.00 Cr".
        return inr_compact(v) if abs(v) >= 1e5 else inr_full(v)
    if unit == "percent":
        return f"{v:.1f}%"
    if unit == "days":
        return f"{v:.0f} days"
    return qty_compact(v)


def fmt_delta(v: Optional[float], unit: str) -> str:
    """Signed change. A change that rounds to zero is shown unsigned ("0.0 pp"),
    never as "-0.0"."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if unit == "percent":
        body, zero = f"{abs(v):.1f} pp", round(abs(v), 1) == 0
    elif unit == "days":
        body, zero = f"{abs(v):.0f} days", round(abs(v)) == 0
    else:
        body, zero = fmt_value(abs(v), unit), abs(v) < 0.005 * (1e7 if unit == "currency" else 1)
    if zero:
        return body.replace("-", "")
    return ("+" if v > 0 else "-") + body


def _py(v: Any) -> Any:
    """JSON-safe scalar: NaN/NaT -> None, numpy -> python."""
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


# ---------------------------------------------------------------------------
# Response envelope pieces
# ---------------------------------------------------------------------------
class ChatTable(BaseModel):
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    totals: Optional[dict[str, Any]] = None
    truncated: bool = False


class ResultBlock(BaseModel):
    id: str
    title: str
    scope: list[str]                    # chips: period + filters
    notes: list[str]
    kpis: list[Kpi]
    charts: list[Chart]
    table: Optional[ChatTable] = None
    table_collapsed: bool = False       # a chart already shows it: offer the table behind a toggle
    empty: bool = False
    message: Optional[str] = None
    spec: dict[str, Any]                # the executed query, echoed back for follow-ups


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
def _tone(m: sem.Measure, v: Optional[float], store) -> str:
    th = m.threshold
    if th is None or v is None:
        return "neutral"
    ref = sem.resolve_ref(th.value, store) if isinstance(th.value, sem.Ref) else th.value
    ok = v >= ref if th.higher_is_better else v <= ref
    return "positive" if ok else "risk"


def build_kpis(rs: ResultSet, store) -> list[Kpi]:
    q = rs.query
    kpis: list[Kpi] = []
    for m in q.measures:
        v = rs.totals.get(m.id)
        note = q.period.label
        delta = None
        if rs.prior_totals is not None:
            pv = rs.prior_totals.get(m.id)
            if pv is not None and v is not None:
                if m.unit in ("percent", "days"):
                    note += f" · vs {fmt_value(pv, m.unit)} in {rs.prior_period.label} ({fmt_delta(v - pv, m.unit)})"
                elif pv != 0:
                    delta = round((v - pv) / abs(pv) * 100, 1)
                    note += f" · vs {fmt_value(pv, m.unit)} in {rs.prior_period.label}"
        if sem.is_point_in_time(m) and rs.snapshot_dates:
            snaps = [d for ds in rs.snapshot_dates.values() for d in ds]
            if snaps:
                note = f"As on {max(snaps):%d %b %Y}"
        kpis.append(Kpi(label=m.label, value=0.0 if v is None else float(v),
                        display=fmt_value(v, m.unit), delta_pct=delta,
                        tone=_tone(m, v, store), note=note))
    return kpis


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------
def _col_type(unit: str) -> str:
    return {"currency": "currency", "percent": "percent", "number": "number",
            "days": "decimal"}[unit]


def _pivot_table(rs: ResultSet) -> Optional[ChatTable]:
    """One measure, one dimension over time: periods as rows and groups as columns
    (the shape people read) instead of 90 long rows."""
    q, df = rs.query, rs.df
    if not (q.grain != "none" and len(q.group_dims) == 1 and len(q.measures) == 1):
        return None
    m, d = q.measures[0], q.group_dims[0]
    if any(f"{m.id}__{x}" in df for x in ("share", "chg", "prior")):
        return None
    groups = list(dict.fromkeys(df[d].astype(str)))
    if len(groups) > PIVOT_MAX_GROUPS:
        return None
    periods = list(dict.fromkeys(df["_period"]))
    val = {(p, str(g)): _py(v) for p, g, v in zip(df["_period"], df[d], df[m.id])}
    ctype = _col_type(m.unit)
    cols = [{"key": "_period", "label": "Period", "type": "text"}]
    cols += [{"key": f"g{i}", "label": g, "type": ctype} for i, g in enumerate(groups)]
    add_total = is_additive(m)
    if add_total:
        cols.append({"key": "_total", "label": "Total", "type": ctype})
    rows = []
    for p in periods:
        row: dict = {"_period": p}
        vals = []
        for i, g in enumerate(groups):
            v = val.get((p, g))
            row[f"g{i}"] = round(v, 2) if isinstance(v, float) else v
            if isinstance(v, (int, float)):
                vals.append(v)
        if add_total:
            row["_total"] = round(sum(vals), 2) if vals else None
        rows.append(row)
    return ChatTable(columns=cols, rows=rows, totals=None, truncated=rs.truncated)


def build_table(rs: ResultSet) -> Optional[ChatTable]:
    q, df = rs.query, rs.df
    if df.empty:
        return None
    pivot = _pivot_table(rs)
    if pivot is not None:
        return pivot
    cols: list[dict] = []
    for d in q.group_dims:
        cols.append({"key": d, "label": sem.DIMENSIONS[d].label, "type": "text"})
    if q.grain != "none":
        cols.append({"key": "_period", "label": "Period", "type": "text"})
    for m in q.measures:
        cols.append({"key": m.id, "label": m.label, "type": _col_type(m.unit)})
        if f"{m.id}__share" in df:
            cols.append({"key": f"{m.id}__share", "label": f"{m.label} - % of total", "type": "percent"})
        if f"{m.id}__chg" in df:
            lab = "change (pp)" if m.unit in ("percent", "days") else "change vs previous period (%)"
            cols.append({"key": f"{m.id}__chg", "label": f"{m.label} - {lab}", "type": "decimal"})
        if f"{m.id}__prior" in df:
            cols.append({"key": f"{m.id}__prior", "label": f"{m.label} - previous period",
                         "type": _col_type(m.unit)})
            cols.append({"key": f"{m.id}__delta", "label": f"{m.label} - change", "type": _col_type(m.unit)
                         if m.unit != "percent" else "decimal"})
            if f"{m.id}__delta_pct" in df:
                cols.append({"key": f"{m.id}__delta_pct", "label": f"{m.label} - change (%)",
                             "type": "decimal"})

    def rnd(key: str, v: Any) -> Any:
        v = _py(v)
        if isinstance(v, float):
            return round(v, 2)
        return v

    rows = [{c["key"]: rnd(c["key"], r.get(c["key"])) for c in cols}
            for r in df.to_dict("records")]

    totals = None
    summable = (q.grain == "none") or all(
        is_additive(m) and not sem.is_point_in_time(m) for m in q.measures)
    if q.group_dims and summable:
        totals = {}
        first = q.group_dims[0]
        for c in cols:
            k = c["key"]
            if k == first:
                totals[k] = "Total"
            elif k in rs.totals:
                totals[k] = rnd(k, rs.totals[k])
            elif k.endswith("__share"):
                totals[k] = 100.0 if q.grain == "none" else None
            elif k.endswith(("__prior", "__delta", "__delta_pct")) and rs.prior_totals:
                mid, kind = k.rsplit("__", 1)
                cur, pri = rs.totals.get(mid), rs.prior_totals.get(mid)
                if cur is None or pri is None:
                    totals[k] = None
                elif kind == "prior":
                    totals[k] = rnd(k, pri)
                elif kind == "delta":
                    totals[k] = rnd(k, cur - pri)
                else:
                    totals[k] = rnd(k, (cur - pri) / abs(pri) * 100) if pri else None
            else:
                totals[k] = None
    return ChatTable(columns=cols, rows=rows, totals=totals, truncated=rs.truncated)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
MAX_COMBO_SERIES = 4


def _combo_chart(cid: str, title: str, x_key: str, rows: list[dict], x_col: str,
                 ms: list[sem.Measure]) -> Chart:
    """Several measures in ONE chart: the first is drawn as bars, the others as
    lines (the dashboards' own combo convention). A measure whose unit differs
    from the bars' (rupees vs days, say) goes on a second axis on the right, so
    both stay readable; the legend and tooltip name each series."""
    ms = ms[:MAX_COMBO_SERIES]
    base = _FORMAT[ms[0].unit]
    series = [
        ChartSeries(
            name=m.label, value_format=_FORMAT[m.unit],
            axis="right" if _FORMAT[m.unit] != base else None,
            data=[{x_key: r[x_col], "value": _num(r[m.id])} for r in rows])
        for m in ms
    ]
    return Chart(id=cid, title=title, type="combo", x_key=x_key, series=series,
                 reference_line=None, value_format=base)


def _group_by_format(measures: list[sem.Measure]) -> dict[str, list[sem.Measure]]:
    out: dict[str, list[sem.Measure]] = {}
    for m in measures:
        out.setdefault(_FORMAT[m.unit], []).append(m)
    return out


def _ref_line(ms: list[sem.Measure], store) -> Optional[float]:
    if len(ms) == 1 and ms[0].reference_line is not None:
        return float(sem.resolve_ref(ms[0].reference_line, store))
    return None


def _num(v: Any) -> float:
    v = _py(v)
    return 0.0 if v is None else round(float(v), 2)


def build_charts(rs: ResultSet, store, block_id: str) -> tuple[list[Chart], list[str]]:
    q, df = rs.query, rs.df
    notes: list[str] = []
    if df.empty or q.chart == "table_only":
        return [], notes
    dims, grain, hint = q.group_dims, q.grain, q.chart
    charts: list[Chart] = []

    def cid(i: int) -> str:
        return f"{block_id}_c{i}"

    # --- A. single figure: KPI cards are the visual -----------------------------
    if not dims and grain == "none":
        return [], notes

    # --- B. trend over time, no breakdown ----------------------------------------
    if not dims and grain != "none" and hint == "combo" and len(q.measures) >= 2:
        rows = [{"_period": r["_period"], **{m.id: r[m.id] for m in q.measures}} for r in df.to_dict("records")]
        return [_combo_chart(cid(0), q.title, "period", rows, "_period", q.measures)], notes
    if not dims and grain != "none":
        for fmt, ms in _group_by_format(q.measures).items():
            ctype = hint if hint in ("line", "bar") else ("line" if len(df) >= 3 else "bar")
            charts.append(Chart(
                id=cid(len(charts)), title=_title(q.title, ms, len(_group_by_format(q.measures))),
                type=ctype, x_key="period",
                series=[ChartSeries(name=m.label, data=[
                    {"period": r["_period"], "value": _num(r[m.id])} for r in df.to_dict("records")])
                    for m in ms],
                reference_line=_ref_line(ms, store), value_format=fmt))
        return charts, notes

    # --- C. one dimension, no time --------------------------------------------------
    if len(dims) == 1 and grain == "none":
        d = dims[0]
        sub = df.head(MAX_CHART_CATEGORIES)
        if len(df) > MAX_CHART_CATEGORIES:
            notes.append(f"The chart shows the top {MAX_CHART_CATEGORIES} of {len(df)}; the table has all of them.")
        longest = max((len(str(x)) for x in sub[d]), default=0)
        if hint == "combo" and len(q.measures) >= 2:
            rows = [{"label": str(r[d]), **{m.id: r[m.id] for m in q.measures}} for r in sub.to_dict("records")]
            if len(q.measures) > MAX_COMBO_SERIES:
                notes.append(f"The chart shows the first {MAX_COMBO_SERIES} measures; the table has all of them.")
            return [_combo_chart(cid(0), q.title, "label", rows, "label", q.measures)], notes
        fmts = _group_by_format(q.measures)
        for fmt, ms in fmts.items():
            donut_ok = (hint == "donut" and len(ms) == 1 and is_additive(ms[0])
                        and len(sub) <= DONUT_MAX_SLICES and (sub[ms[0].id].fillna(0) >= 0).all())
            if hint == "donut" and not donut_ok:
                notes.append("A pie/donut only suits shares of an additive total with a few slices, so a bar chart is shown.")
            if donut_ok:
                ctype = "donut"
            elif hint in ("bar", "hbar"):
                ctype = hint
            else:
                ctype = "hbar" if (len(sub) > 6 or longest > 14) else "bar"
            charts.append(Chart(
                id=cid(len(charts)), title=_title(q.title, ms, len(fmts)),
                type=ctype, x_key="label",
                series=[ChartSeries(name=m.label, data=[
                    {"label": str(r[d]), "value": _num(r[m.id])} for r in sub.to_dict("records")])
                    for m in ms],
                reference_line=None, value_format=fmt))
        return charts, notes

    # --- D. one dimension over time ---------------------------------------------------
    if len(dims) == 1 and grain != "none":
        d = dims[0]
        order = list(dict.fromkeys(df[d]))                 # ranked overall by the engine
        periods = list(dict.fromkeys(df["_period"]))
        shown = q.measures[:2]
        for m in shown:
            title = q.title if len(shown) == 1 else f"{q.title} - {m.label}"
            additive = is_additive(m)
            fold = (hint in ("auto", "stacked_bar") and additive and len(order) > MAX_STACK_GROUPS)
            if hint == "stacked_bar" and additive or fold:
                top = order[:MAX_STACK_GROUPS] if fold else order[:MAX_CHART_SERIES]
                series = []
                for g in top:
                    gdf = df[df[d] == g].set_index("_period")
                    series.append(ChartSeries(name=str(g), data=[
                        {"period": p, "value": _num(gdf[m.id].get(p))} for p in periods]))
                rest = df[~df[d].isin(top)]
                if len(rest):
                    other = rest.groupby("_period")[m.id].sum(min_count=1)
                    series.append(ChartSeries(name="All others", data=[
                        {"period": p, "value": _num(other.get(p))} for p in periods]))
                    notes.append(f"The {len(order) - len(top)} smaller {sem.DIMENSIONS[d].label.lower()} values are combined as \"All others\" in the chart.")
                ctype = "stacked_bar"
            else:
                top = order[:MAX_CHART_SERIES]
                if len(order) > MAX_CHART_SERIES:
                    notes.append(f"The chart shows the top {MAX_CHART_SERIES} of {len(order)}; the table has all of them.")
                series = []
                for g in top:
                    gdf = df[df[d] == g].set_index("_period")
                    series.append(ChartSeries(name=str(g), data=[
                        {"period": p, "value": _num(gdf[m.id].get(p))} for p in periods]))
                ctype = "bar" if hint == "bar" else "line"
            charts.append(Chart(id=cid(len(charts)), title=title, type=ctype, x_key="period",
                                series=series, reference_line=None, value_format=_FORMAT[m.unit]))
        if len(q.measures) > 2:
            notes.append("Charts cover the first two measures; the table has all of them.")
        return charts, list(dict.fromkeys(notes))

    # --- E. two dimensions, no time ----------------------------------------------------
    d0, d1 = dims
    cats = list(dict.fromkeys(df[d0]))[:MAX_CHART_CATEGORIES]
    sers = list(dict.fromkeys(df[d1]))
    if len(sers) > MAX_CHART_SERIES:
        notes.append(f"Too many {sem.DIMENSIONS[d1].label.lower()} values to chart clearly ({len(sers)}); see the table.")
        return [], notes
    for m in q.measures[:2]:
        stack = hint == "stacked_bar" and is_additive(m)
        series = []
        for s_ in sers:
            sdf = df[df[d1] == s_].set_index(d0)
            series.append(ChartSeries(name=str(s_), data=[
                {"label": str(c), "value": _num(sdf[m.id].get(c))} for c in cats]))
        charts.append(Chart(id=cid(len(charts)),
                            title=q.title if len(q.measures[:2]) == 1 else f"{q.title} - {m.label}",
                            type="stacked_bar" if stack else ("hbar" if len(cats) > 6 else "bar"),
                            x_key="label", series=series, reference_line=None,
                            value_format=_FORMAT[m.unit]))
    return charts, notes


def _title(base: str, ms: list[sem.Measure], n_groups: int) -> str:
    return base if n_groups == 1 else f"{base} - {', '.join(m.label for m in ms)}"


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
def scope_chips(rs: ResultSet) -> list[str]:
    q = rs.query
    chips = [q.period.label]
    for f in q.filters:
        label = sem.DIMENSIONS[f.dim_id].label
        vals = ", ".join(f.labels[:4]) + ("…" if len(f.labels) > 4 else "")
        chips.append(f"{label}{' not' if f.op == 'not_in' else ''}: {vals}")
    if q.group_dims:
        chips.append("By " + " × ".join(sem.DIMENSIONS[d].label.lower() for d in q.group_dims))
    if q.grain != "none":
        chips.append({"month": "Monthly", "quarter": "Quarterly", "fiscal_year": "By fiscal year",
                      "year": "By year"}[q.grain])
    return chips


def build_block(rs: ResultSet, store, block_id: str) -> ResultBlock:
    q = rs.query
    spec = q.spec.model_dump(mode="json")
    if rs.empty:
        return ResultBlock(id=block_id, title=q.title, scope=scope_chips(rs), notes=rs.notes,
                           kpis=[], charts=[], table=None, empty=True,
                           message=rs.empty_reason or "No data for that selection.", spec=spec)
    charts, chart_notes = build_charts(rs, store, block_id)
    show_kpis = not q.group_dims and q.grain == "none"
    return ResultBlock(
        id=block_id, title=q.title, scope=scope_chips(rs),
        notes=list(dict.fromkeys(rs.notes + chart_notes)),
        kpis=build_kpis(rs, store) if show_kpis else [],
        charts=charts,
        table=None if show_kpis else build_table(rs),
        table_collapsed=bool(charts),      # table only competes with a chart when there is one
        spec=spec,
    )
