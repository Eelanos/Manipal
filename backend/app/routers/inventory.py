"""Inventory Analysis dashboard. Matches PRAVAH's page structure."""

from dataclasses import replace
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends

from app import metrics
from app.config import DATA_END, DATA_START
from app.data_loader import DataStore, get_store
from app.filters import Filters, apply, get_filters
from app.formatting import inr_compact
from app.schemas import Chart, ChartSeries, DashboardResponse, Kpi, Table

router = APIRouter(prefix="/api", tags=["inventory"])

AGE_ORDER = ["Below 30", "30 - 60", "60 - 90", "Above 90"]

# Stock Ageing colours: Below 30 stays the dark teal, 30-60 and Above 90 trade
# places so that Above 90 (the slow stock) is the red one.
AGE_COLORS = {"Below 30": "#3d6479", "30 - 60": "#5bbcd6", "60 - 90": "#2f54d4", "Above 90": "#c0392b"}


# ---------------------------------------------------------------------------
# Year-on-year arrows on the KPI cards
# ---------------------------------------------------------------------------
def _pct_change(cur: float, prev: Optional[float]) -> Optional[float]:
    """% change vs last year, or None when there is nothing to compare with."""
    if prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def _yoy_kpi(label: str, value: float, display: str, prev: Optional[float], vs_text: str,
             basis: str, higher_is: str = "neutral", note: Optional[str] = None,
             cur: Optional[float] = None) -> Kpi:
    """A KPI card with its year-on-year arrow.

    higher_is: "worse" -> an increase is shown red (more days of stock is bad),
    "neutral" -> the arrow is grey (more stock value is neither good nor bad).
    When last year's figure does not exist the card says so instead of
    inventing an arrow."""
    # `cur` is the figure the arrow is judged on when it differs from the card's
    # own value (consumption: only the months that have a last-year twin).
    d = _pct_change(value if cur is None else cur, prev)
    if d is None:
        return Kpi(label=label, value=value, display=display, note=note,
                   delta_label="no last-year data", delta_basis=basis)
    good = None if higher_is == "neutral" else (d <= 0 if higher_is == "worse" else d >= 0)
    return Kpi(label=label, value=value, display=display, note=note, delta_pct=d,
               delta_label=vs_text, delta_good=good, delta_basis=basis)


def _month_text(a: pd.Timestamp, b: pd.Timestamp) -> str:
    """'Dec 25', 'Jan-Dec 25' or 'Jan 25-Mar 26' for a date range."""
    if (a.year, a.month) == (b.year, b.month):
        return f"{a:%b %y}"
    return f"{a:%b}-{b:%b %y}" if a.year == b.year else f"{a:%b %y}-{b:%b %y}"


@router.get("/inventory-analysis", response_model=DashboardResponse)
def inventory_dashboard(
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> DashboardResponse:
    df = apply(store.inventory, f, date_col="Date")
    cons = apply(store.consumption, f, date_col="Date")
    bud = apply(store.budget, f, date_col="Date")

    if not len(df):
        return DashboardResponse(
            filters=f.as_dict(), kpis=[], charts=[],
            table=Table(columns=[], rows=[]),
            insights=[], row_count=0,
        )

    # Stock is a point-in-time measure - summing month-end snapshots across a
    # range double-counts the same physical stock. Every stock KPI reads from
    # the latest snapshot ("as on"), matching the client's own "(As on)" label.
    as_on = df["Date"].max()
    snap = df[df["Date"] == as_on]

    k = metrics.inventory_kpis(snap)
    h = metrics.his_consumption(cons)

    days_series = metrics.inventory_days_series(df, cons)
    budget_days_series = metrics.budget_inventory_days_series(df, bud)
    latest_days = float(days_series["inventory_days"].iloc[-1]) if len(days_series) else 0.0

    in_transit = float(snap["In_Transit_Value"].sum())
    above_90 = float(snap.loc[snap["Ageing"] == "Above 90", "Stock_Value"].sum())

    # ---- last year's figures, for the up/down arrows -----------------------------
    # Same filters (unit, department, group) but the whole date range, so last
    # year's month is available even when the selected period starts after it.
    f_all = replace(f, date_from=DATA_START, date_to=DATA_END)
    inv_all = apply(store.inventory, f_all, date_col="Date")
    cons_all = apply(store.consumption, f_all, date_col="Date")
    ly_month = as_on.replace(day=1) - pd.DateOffset(years=1)
    ly_snap_all = inv_all[inv_all["Month_Start"] == ly_month]
    ly_snap = ly_snap_all[ly_snap_all["Date"] == ly_snap_all["Date"].max()] if len(ly_snap_all) else ly_snap_all
    has_ly = len(ly_snap) > 0
    ly_text = f"{ly_month:%b %y}"

    ly_days = ly_value = ly_transit = ly_above_90 = None
    if has_ly:
        ly_date = ly_snap["Date"].iloc[0]
        all_days = metrics.inventory_days_series(inv_all, cons_all)
        match = all_days.loc[all_days["Date"] == ly_date, "inventory_days"]
        ly_days = float(match.iloc[0]) if len(match) else None
        ly_value = float(ly_snap["Stock_Value"].sum())
        ly_transit = float(ly_snap["In_Transit_Value"].sum())
        ly_above_90 = float(ly_snap.loc[ly_snap["Ageing"] == "Above 90", "Stock_Value"].sum())

    # Consumption is a flow over the selected period. It is compared with the
    # same period a year earlier, but only for the months that HAVE a last-year
    # twin in the data (with Full Range that is Jan-Dec 26 vs Jan-Dec 25) so the
    # two sides always cover the same number of days.
    a, b = pd.Timestamp(f.date_from), pd.Timestamp(f.date_to)
    first_comparable = pd.Timestamp(DATA_START) + pd.DateOffset(years=1)
    a2 = max(a, first_comparable)
    ly_cons = None
    cons_vs, cons_basis, cons_cur = "no last-year data", "No data exists for the same months last year.", h["non_implant_cons"]
    if a2 <= b:
        cur_rows = cons_all[(cons_all["Date"] >= a2) & (cons_all["Date"] <= b)]
        prev_a, prev_b = a2 - pd.DateOffset(years=1), b - pd.DateOffset(years=1)
        prev_rows = cons_all[(cons_all["Date"] >= prev_a) & (cons_all["Date"] <= prev_b)]
        if len(prev_rows):
            cons_cur = metrics.his_consumption(cur_rows)["non_implant_cons"]
            ly_cons = metrics.his_consumption(prev_rows)["non_implant_cons"]
            cons_vs = f"vs {_month_text(prev_a, prev_b)}"
            cons_basis = (f"Consumption in {_month_text(a2, b)} compared with {_month_text(prev_a, prev_b)} "
                          f"(only months that have a last-year twin in the data).")

    stock_basis = f"Latest month ({as_on:%b %y}) compared with the same month last year ({ly_text})."
    # Only the client's own 5-KPI row - no second row.
    kpis = [
        _yoy_kpi("Inventory Days", latest_days, f"{latest_days:.0f}", ly_days, f"vs {ly_text}",
                 stock_basis, higher_is="worse",
                 note="Stock value x days elapsed / consumption month-to-date"),
        _yoy_kpi("Inventory Value", k["total_stock_value"], inr_compact(k["total_stock_value"]),
                 ly_value, f"vs {ly_text}", stock_basis,
                 note=f"As on {as_on.strftime('%d %b %Y')}"),
        _yoy_kpi("Stock in Transit", in_transit, inr_compact(in_transit),
                 ly_transit, f"vs {ly_text}", stock_basis,
                 note="Ordered, not yet received"),
        # The former "HIS Consumption" card now reads "Actual Consumption" and
        # carries the non-implant figure (the old "HIS Non-Implant Cons" card).
        _yoy_kpi("Actual Consumption", h["non_implant_cons"], inr_compact(h["non_implant_cons"]),
                 ly_cons, cons_vs, cons_basis, cur=cons_cur,
                 note=f"Excludes {inr_compact(h['implant_cons'])} of implants"),
        _yoy_kpi("Stock Ageing Above 90", above_90, inr_compact(above_90),
                 ly_above_90, f"vs {ly_text}", stock_basis, higher_is="worse",
                 note=f"{metrics.safe_pct(above_90, k['total_stock_value']):.1f}% of stock value, as on {as_on.strftime('%d %b %Y')}"),
    ]

    charts = []

    # 1. Inventory Days Trend - Inventory Days (bars) + BUD (line).
    if len(days_series):
        act_map = dict(zip(days_series["Date"], days_series["inventory_days"]))
        bud_map = dict(zip(budget_days_series["Date"], budget_days_series["budget_inventory_days"])) \
            if len(budget_days_series) else {}
        months = sorted(act_map)
        charts.append(Chart(
            id="inventory_days_trend", title="Inventory Days Trend",
            type="combo", x_key="month", value_format="number",
            # "combo" draws the FIRST series as bars and the rest as lines, so
            # Inventory Days goes first (bars) and BUD second (line).
            series=[
                ChartSeries(name="Inventory Days", data=[
                    {"month": m.strftime("%b %y"), "value": float(act_map[m])}
                    for m in months]),
                ChartSeries(name="BUD", data=[
                    {"month": m.strftime("%b %y"), "value": float(bud_map.get(m, 0))}
                    for m in months]),
            ],
            hint="Click on a month to get unit wise details",
            # Click a month -> a table of Unit, Stock and Inventory Days for it.
            drilldown=metrics.stock_and_days_by_unit(df, cons),
        ))

    # 2. Closing Stock Ageing (Cr) - monthly stacked bar (moved here from the
    # Consumption page).
    age_rows = []
    for month, grp in df.groupby("Month_Start"):
        row = {"month": month.strftime("%b %y")}
        for bucket in AGE_ORDER:
            row[bucket] = float(grp.loc[grp["Ageing"] == bucket, "Stock_Value"].sum())
        age_rows.append(row)
    charts.append(Chart(
        id="closing_stock_ageing", title="Stock Ageing (Cr)",
        type="stacked_bar", x_key="month",
        series=[ChartSeries(name=b, color=AGE_COLORS[b], data=[
            {"month": r["month"], "value": r[b]} for r in age_rows])
            for b in AGE_ORDER],
        # Click a month -> a table of Unit x ageing bucket.
        drilldown=metrics.ageing_by_unit(df),
    ))

    # 3. Slow Moving Inventory Trend (%).
    nm_rows = []
    for month, grp in df.groupby("Month_Start"):
        tot = grp["Stock_Value"].sum()
        nm = grp[grp["Moving/Non Moving"] == "Non Moving"]
        nm_rows.append({
            "month": month.strftime("%b %y"),
            "non_moving": metrics.safe_pct(nm["Stock_Value"].sum(), tot),
            "essential": metrics.safe_pct(
                grp.loc[grp["Is_Essential"] == True, "Stock_Value"].sum(), tot),  # noqa: E712
        })
    charts.append(Chart(
        id="non_moving_trend", title="Slow Moving Inventory Trend (%)",
        type="line", x_key="month", value_format="percent",
        series=[
            ChartSeries(name="Non Moving %", data=[
                {"month": r["month"], "value": r["non_moving"]} for r in nm_rows]),
            # Same figure as the former "Essential Stock %" series, renamed on request.
            ChartSeries(name="Slow Moving Stock %", data=[
                {"month": r["month"], "value": r["essential"]} for r in nm_rows]),
        ],
        drilldown=metrics.non_moving_by_dept(df),
    ))

    # 4. Expiry Risk Trend: Near Expiry and Expiry stock value per month, side by
    # side. Double drill-down: click a month -> units, click a unit -> departments
    # (both live in the one drilldown dictionary, see metrics.expiry_by_unit_and_dept).
    exp_rows = metrics.expiry_value_by_month(df)
    charts.append(Chart(
        id="expiry_risk", title="Expiry Risk Trend (Cr)",
        type="bar", x_key="month", value_format="currency",
        series=[
            ChartSeries(name="Near Expiry", color="#e08a1e", data=[
                {"month": r["month"], "value": r["near"]} for r in exp_rows]),
            ChartSeries(name="Expiry", color="#c0392b", data=[
                {"month": r["month"], "value": r["expired"]} for r in exp_rows]),
        ],
        drilldown=metrics.expiry_by_unit_and_dept(df),
    ))

    detail = snap[["Item_Name", "Batch_No", "Expiry_Date", "Stock_Qty",
                   "Stock_Value", "Ageing", "Expiry/Near Expiry",
                   "Moving/Non Moving", "Is_Essential"]].copy()
    detail = detail.sort_values("Stock_Value", ascending=False).head(500)
    table = Table(
        columns=[
            {"key": "Item_Name", "label": "Item", "type": "text"},
            {"key": "Batch_No", "label": "Batch", "type": "text"},
            {"key": "Expiry_Date", "label": "Expiry", "type": "text"},
            {"key": "Stock_Qty", "label": "Qty", "type": "number"},
            {"key": "Stock_Value", "label": "Stock Value", "type": "currency"},
            {"key": "Ageing", "label": "Ageing", "type": "text"},
            {"key": "essential", "label": "Essential", "type": "text"},
            {"key": "flag", "label": "Status", "type": "text"},
        ],
        rows=[{
            "Item_Name": r["Item_Name"], "Batch_No": r["Batch_No"],
            "Expiry_Date": r["Expiry_Date"].strftime("%d %b %Y"),
            "Stock_Qty": int(r["Stock_Qty"]), "Stock_Value": float(r["Stock_Value"]),
            "Ageing": r["Ageing"],
            "essential": "Yes" if r["Is_Essential"] else "",
            "flag": r["Expiry/Near Expiry"] if isinstance(r["Expiry/Near Expiry"], str)
                    else r["Moving/Non Moving"],
        } for _, r in detail.iterrows()],
    )

    # Key Observations removed for this page per request.
    return DashboardResponse(
        filters=f.as_dict(), kpis=kpis, charts=charts, table=table,
        insights=[], row_count=len(df),
    )