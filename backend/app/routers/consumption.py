"""Consumption dashboard endpoint."""

from fastapi import APIRouter, Depends

from app import metrics
from app.data_loader import DataStore, get_store
from app.filters import ALL, Filters, apply, get_filters
from app.formatting import inr_compact, pct, qty_compact
from app.schemas import Chart, ChartSeries, DashboardResponse, Kpi, Table

router = APIRouter(prefix="/api", tags=["consumption"])


@router.get("/consumption", response_model=DashboardResponse)
def consumption_dashboard(
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> DashboardResponse:
    df = apply(store.consumption, f, date_col="Date")

    if not len(df):
        return DashboardResponse(
            filters=f.as_dict(), kpis=[], charts=[],
            table=Table(columns=[], rows=[]),
            insights=["No consumption recorded for the selected filters."],
            row_count=0,
        )

    k = metrics.consumption_kpis(df)

    # --- Budget --------------------------------------------------------
    # Budget has no Stock Take Group dimension, so it is withheld when that
    # filter is active rather than compared against a partial actual.
    budget_available = f.stock_take_group == ALL
    bud_monthly = None
    bk = None
    if budget_available:
        bud_df = apply(store.budget, f, date_col="Date")
        bud_monthly = metrics.budget_by_month(bud_df)
        bud_total = float(bud_monthly["Budget_Value"].sum()) if len(bud_monthly) else 0.0
        if bud_total:
            bk = metrics.budget_kpis(k["total_value"], bud_total)

    kpis = [
        Kpi(label="Total Consumption Value", value=k["total_value"],
            display=inr_compact(k["total_value"])),
        Kpi(label="Total Qty Consumed", value=k["total_qty"],
            display=qty_compact(k["total_qty"])),
        Kpi(label="IP Share", value=k["ip_pct"], display=pct(k["ip_pct"])),
    ]
    if bk:
        kpis.insert(1, Kpi(
            label="Budget", value=bk["budget_value"],
            display=inr_compact(bk["budget_value"])))
        kpis.insert(2, Kpi(
            label="Budget Utilisation", value=bk["utilisation_pct"],
            display=pct(bk["utilisation_pct"]),
            delta_pct=bk["variance_pct"],
            tone="risk" if bk["utilisation_pct"] > 100 else "neutral"))

    charts = []

    # Inventory is needed for the Consumption Trend drill-down (unit-wise stock
    # and inventory days) and for the location-wise inventory chart below.
    inv = apply(store.inventory, f, date_col="Date")

    # 1. Consumption Trend - Actual (bars) vs Budget (line) by month.
    if bud_monthly is not None and len(bud_monthly):
        act_monthly = metrics.monthly_trend(df)
        bud_map = dict(zip(bud_monthly["Month_Start"], bud_monthly["Budget_Value"]))
        act_map = dict(zip(act_monthly["Month_Start"], act_monthly["Value"]))
        months = sorted(set(act_map) | set(bud_map))
        charts.append(Chart(
            id="consumption_trend", title="Consumption Trend", type="combo",
            x_key="month",
            # "combo" draws the FIRST series as bars and the rest as lines,
            # so ACT goes first (bars) and BUD second (line).
            series=[
                ChartSeries(name="ACT", data=[
                    {"month": m.strftime("%b %y"), "value": float(act_map.get(m, 0))}
                    for m in months]),
                ChartSeries(name="BUD", data=[
                    {"month": m.strftime("%b %y"), "value": float(bud_map.get(m, 0))}
                    for m in months]),
            ],
            # Click a month -> unit-wise stock and inventory days.
            drilldown=metrics.stock_and_days_by_unit(inv, df),
        ))

    # 2. Top 10 by store location - consumption.
    # FAKE DIMENSION: Store_Location doesn't exist in real hospital data we
    # have; it's generated (add_store_location.py) to mirror the client's
    # location-level breakdown. Clearly labelled, not read off any document.
    # The chart is only drawn when the loaded data actually has that column (a data set without
    # it simply has no location charts, instead of the whole page failing).
    has_loc = "Store_Location" in df.columns
    if has_loc:
        loc = metrics.breakdown(df, "Store_Location", top_n=10)
        charts.append(Chart(
            id="top_locations_consumption",
            title="Top 10 Location-wise Consumption", type="hbar", x_key="label",
            series=[ChartSeries(name="Value", data=[
                {"label": r["Store_Location"], "value": float(r["Value"])}
                for _, r in loc.iterrows()])],
                drilldown=metrics.consumption_by_item_for_location(df),
        ))

    # 3. Top 10 by store location - inventory value (latest snapshot).
    if len(inv) and "Store_Location" in inv.columns:
        as_on = inv["Date"].max()
        snap = inv[inv["Date"] == as_on]
        loc_inv = metrics.breakdown(snap, "Store_Location", value_col="Stock_Value", top_n=10)
        charts.append(Chart(
            id="top_locations_inventory",
            title="Top 10 Location-wise Inventory Value", type="bar", x_key="label",
            series=[ChartSeries(name="Stock Value", data=[
                {"label": r["Store_Location"], "value": float(r["Stock_Value"])}
                for _, r in loc_inv.iterrows()])],
                drilldown=metrics.inventory_by_item_for_location(snap),
        ))

    agg = (df.groupby(["Item_ID", "Item_Name", "Category"], as_index=False)
             .agg(Qty=("Qty", "sum"), Value=("Value", "sum"))
             .sort_values("Value", ascending=False))
    total = k["total_value"]
    table = Table(
        columns=[
            {"key": "Item_ID", "label": "Item ID", "type": "text"},
            {"key": "Item_Name", "label": "Item", "type": "text"},
            {"key": "Category", "label": "Category", "type": "text"},
            {"key": "Qty", "label": "Qty", "type": "number"},
            {"key": "Value", "label": "Value", "type": "currency"},
            {"key": "share_pct", "label": "% of Total", "type": "percent"},
        ],
        rows=[{
            "Item_ID": r["Item_ID"], "Item_Name": r["Item_Name"],
            "Category": r["Category"], "Qty": int(r["Qty"]),
            "Value": float(r["Value"]),
            "share_pct": metrics.safe_pct(r["Value"], total),
        } for _, r in agg.iterrows()],
    )

    insights = []
    if bk:
        over = "over" if bk["variance_value"] > 0 else "under"
        insights.append(
            f"Consumption is {abs(bk['variance_pct']):.1f}% {over} budget "
            f"({inr_compact(k['total_value'])} against a plan of "
            f"{inr_compact(bk['budget_value'])}).")
    elif not budget_available:
        insights.append(
            "Budget is planned by department, not by stock take group - "
            "clear the group filter to compare against plan.")
    if has_loc and len(loc):
        insights.append(
            f"{loc.iloc[0]['Store_Location']} is the top consumption "
            f"location at {inr_compact(loc.iloc[0]['Value'])}.")
    if has_loc:
        insights.append(
            "Location-wise breakdowns use a synthetic Store Location - the real "
            "data has no in-hospital location dimension. Structure matches the "
            "client's report; the specific locations are illustrative.")

    return DashboardResponse(
        filters=f.as_dict(), kpis=kpis, charts=charts, table=table,
        insights=insights, row_count=len(df),
    )