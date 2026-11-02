"""Inventory Analysis dashboard. Matches PRAVAH's page structure."""

from fastapi import APIRouter, Depends

from app import metrics
from app.data_loader import DataStore, get_store
from app.filters import Filters, apply, get_filters
from app.formatting import inr_compact
from app.schemas import Chart, ChartSeries, DashboardResponse, Kpi, Table

router = APIRouter(prefix="/api", tags=["inventory"])

AGE_ORDER = ["Below 30", "30 - 60", "60 - 90", "Above 90"]


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

    # Only the client's own 5-KPI row - no second row.
    kpis = [
        Kpi(label="Inventory Days", value=latest_days,
            display=f"{latest_days:.0f}",
            note="Stock value x days elapsed / consumption month-to-date"),
        Kpi(label="Inventory Value", value=k["total_stock_value"],
            display=inr_compact(k["total_stock_value"]),
            note=f"As on {as_on.strftime('%d %b %Y')}"),
        Kpi(label="Stock in Transit", value=in_transit,
            display=inr_compact(in_transit),
            note="Ordered, not yet received"),
        Kpi(label="HIS Consumption", value=h["his_cons"],
            display=inr_compact(h["his_cons"])),
        Kpi(label="HIS Non-Implant Cons", value=h["non_implant_cons"],
            display=inr_compact(h["non_implant_cons"]),
            note=f"Excludes {inr_compact(h['implant_cons'])} of implants"),
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
            drilldown=metrics.inventory_days_by_dept(df, cons),
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
        id="closing_stock_ageing", title="Closing Stock Ageing (Cr)",
        type="stacked_bar", x_key="month",
        series=[ChartSeries(name=b, data=[
            {"month": r["month"], "value": r[b]} for r in age_rows])
            for b in AGE_ORDER],
        drilldown=metrics.closing_stock_by_dept(df),
    ))

    # 3. Non Moving Inventory Trend (%).
    nm_rows = []
    for month, grp in df.groupby("Month_Start"):
        tot = grp["Stock_Value"].sum()
        nm = grp[grp["Moving/Non Moving"] == "Non Moving"]
        nm_recent = nm[nm["Ageing"] == "Below 30"]
        nm_rows.append({
            "month": month.strftime("%b %y"),
            "non_moving": metrics.safe_pct(nm["Stock_Value"].sum(), tot),
            "non_moving_recent": metrics.safe_pct(nm_recent["Stock_Value"].sum(), tot),
            "essential": metrics.safe_pct(
                grp.loc[grp["Is_Essential"] == True, "Stock_Value"].sum(), tot),  # noqa: E712
        })
    charts.append(Chart(
        id="non_moving_trend", title="Non Moving Inventory Trend (%)",
        type="line", x_key="month", value_format="percent",
        series=[
            ChartSeries(name="Non Moving %", data=[
                {"month": r["month"], "value": r["non_moving"]} for r in nm_rows]),
            ChartSeries(name="Non Moving Recent Purchase %", data=[
                {"month": r["month"], "value": r["non_moving_recent"]} for r in nm_rows]),
            ChartSeries(name="Essential Stock %", data=[
                {"month": r["month"], "value": r["essential"]} for r in nm_rows]),
        ],
        drilldown=metrics.non_moving_by_dept(df),
    ))

    # 4. Expiry Risk Trend (%).
    exp_rows = []
    for month, grp in df.groupby("Month_Start"):
        tot = grp["Stock_Value"].sum()
        exp_rows.append({
            "month": month.strftime("%b %y"),
            "near": metrics.safe_pct(
                grp.loc[grp["Expiry/Near Expiry"] == "Near Expiry", "Stock_Value"].sum(), tot),
            "expired": metrics.safe_pct(
                grp.loc[grp["Expiry/Near Expiry"] == "Expired", "Stock_Value"].sum(), tot),
        })
    charts.append(Chart(
        id="expiry_risk", title="Expiry Risk Trend (% of stock value)",
        type="line", x_key="month", value_format="percent",
        series=[
            ChartSeries(name="Near Expiry %", data=[
                {"month": r["month"], "value": r["near"]} for r in exp_rows]),
            ChartSeries(name="Expired %", data=[
                {"month": r["month"], "value": r["expired"]} for r in exp_rows]),
        ],
        drilldown=metrics.expiry_risk_by_dept(df),
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