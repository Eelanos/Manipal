"""Inventory Analysis dashboard: year-on-year KPI arrows, renamed/reshaped charts and the
three drill-downs (unit table, ageing table, two-level expiry). Figures are recomputed
straight from the raw tables, a different way from the router."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.data_loader import get_store
from app.main import app

client = TestClient(app)
STORE = get_store()


@pytest.fixture(scope="module")
def dash():
    r = client.get("/api/inventory-analysis")
    assert r.status_code == 200
    return r.json()


def chart(d, cid):
    return next(c for c in d["charts"] if c["id"] == cid)


def test_kpis_are_the_five_requested_cards_each_with_a_yoy_comparison(dash):
    labels = [k["label"] for k in dash["kpis"]]
    assert labels == ["Inventory Days", "Inventory Value", "Stock in Transit",
                      "Actual Consumption", "Stock Ageing Above 90"]
    assert "HIS Consumption" not in labels and "HIS Non Implant Consumption" not in labels
    for k in dash["kpis"]:
        assert k["delta_label"]            # every card says what it is compared with
        assert k["delta_pct"] is not None  # full range has last-year twins


def test_inventory_value_arrow_matches_the_same_month_a_year_earlier(dash):
    inv = STORE.inventory
    last = inv["Date"].max()
    prev = last - pd.DateOffset(years=1)
    cur = inv.loc[inv["Date"] == last, "Stock_Value"].sum()
    old = inv.loc[(inv["Date"].dt.year == prev.year) & (inv["Date"].dt.month == prev.month)
                  & (inv["Date"] == inv.loc[(inv["Date"].dt.year == prev.year)
                                            & (inv["Date"].dt.month == prev.month), "Date"].max()),
                  "Stock_Value"].sum()
    k = next(k for k in dash["kpis"] if k["label"] == "Inventory Value")
    assert k["delta_pct"] == pytest.approx((cur - old) / old * 100, abs=0.06)


def test_stock_ageing_above_90_card_is_the_latest_snapshots_above_90_value(dash):
    inv = STORE.inventory
    snap = inv[inv["Date"] == inv["Date"].max()]
    k = next(k for k in dash["kpis"] if k["label"] == "Stock Ageing Above 90")
    assert k["value"] == pytest.approx(snap.loc[snap["Ageing"] == "Above 90", "Stock_Value"].sum())


def test_actual_consumption_excludes_implants(dash):
    cons = STORE.consumption
    k = next(k for k in dash["kpis"] if k["label"] == "Actual Consumption")
    assert k["value"] < cons["Value"].sum()          # implants were taken out


def test_a_range_without_a_last_year_says_so_instead_of_inventing_an_arrow():
    r = client.get("/api/inventory-analysis", params={"preset": "fy2025"}).json()
    if r["row_count"] == 0:
        pytest.skip("preset not available")
    assert any(k["delta_pct"] is None and k["delta_label"] == "no last-year data" for k in r["kpis"])


def test_renamed_charts_and_hint(dash):
    titles = {c["id"]: c["title"] for c in dash["charts"]}
    assert titles["closing_stock_ageing"] == "Stock Ageing (Cr)"
    assert titles["non_moving_trend"] == "Slow Moving Inventory Trend (%)"
    assert chart(dash, "inventory_days_trend")["hint"] == "Click on a month to get unit wise details"
    names = [s["name"] for s in chart(dash, "non_moving_trend")["series"]]
    assert names == ["Non Moving %", "Slow Moving Stock %"]       # recent purchase removed


def test_stock_ageing_order_and_colours(dash):
    ser = chart(dash, "closing_stock_ageing")["series"]
    assert [s["name"] for s in ser] == ["Below 30", "30 - 60", "60 - 90", "Above 90"]
    colour = {s["name"]: s["color"] for s in ser}
    assert colour["Above 90"] == "#c0392b"                         # red
    assert len(set(colour.values())) == 4


def test_inventory_days_drilldown_is_a_unit_table(dash):
    dd = chart(dash, "inventory_days_trend")["drilldown"]
    month, rows = next(iter(dd.items()))
    assert set(rows[0]) == {"Unit", "Stock", "Inventory Days"}
    assert len(rows) == STORE.inventory["Unit_Name"].nunique()


def test_ageing_drilldown_rows_add_up_to_the_bar(dash):
    c = chart(dash, "closing_stock_ageing")
    bars = {m: sum(s["data"][i]["value"] for s in c["series"])
            for i, m in enumerate(d["month"] for d in c["series"][0]["data"])}
    for month, rows in c["drilldown"].items():
        assert set(rows[0]) == {"Unit", "Below 30", "30 - 60", "60 - 90", "Above 90"}
        assert sum(r[b] for r in rows for b in ("Below 30", "30 - 60", "60 - 90", "Above 90")) == pytest.approx(bars[month])


def test_expiry_chart_is_two_bars_per_month_and_drills_two_levels(dash):
    c = chart(dash, "expiry_risk")
    assert c["type"] == "bar" and [s["name"] for s in c["series"]] == ["Near Expiry", "Expiry"]
    dd = c["drilldown"]
    for i, d in enumerate(c["series"][0]["data"]):
        month = d["month"]
        units = dd[month]
        assert set(units[0]) == {"Unit", "Near Expiry", "Expiry"}
        # level 1 adds up to the bar, level 2 adds up to its unit row
        assert sum(u["Near Expiry"] for u in units) == pytest.approx(d["value"])
        assert sum(u["Expiry"] for u in units) == pytest.approx(c["series"][1]["data"][i]["value"])
        for u in units:
            depts = dd[f"{month}|{u['Unit']}"]
            assert set(depts[0]) == {"Department", "Near Expiry", "Expiry"}
            assert sum(x["Near Expiry"] for x in depts) == pytest.approx(u["Near Expiry"])
            assert sum(x["Expiry"] for x in depts) == pytest.approx(u["Expiry"])
