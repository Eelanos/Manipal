"""
Store Location (a generated dimension, see add_store_location.py) must show up consistently on the Consumption
charts, in Ask QBER and in RCA - and the pages must still work for a data set that does not have the column.
"""

import copy

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.data_loader import get_store
from app.filters import Filters
from app.main import app
from app.rca import engine as rca_engine

client = TestClient(app)
STORE = get_store()


def _chart(body, cid):
    return next((c for c in body["charts"] if c["id"] == cid), None)


def test_data_has_store_location_on_both_tables():
    for df in (STORE.consumption, STORE.inventory):
        assert "Store_Location" in df.columns and df["Store_Location"].notna().all()


def test_consumption_location_charts_match_pandas():
    body = client.get("/api/consumption").json()
    c = STORE.consumption
    want = c.groupby("Store_Location")["Value"].sum().sort_values(ascending=False).head(10)
    ch = _chart(body, "top_locations_consumption")
    assert ch is not None
    got = {r["label"]: r["value"] for r in ch["series"][0]["data"]}
    assert got == pytest.approx(want.to_dict())

    i = STORE.inventory
    snap = i[i["Date"] == i["Date"].max()]
    want_i = snap.groupby("Store_Location")["Stock_Value"].sum().sort_values(ascending=False).head(10)
    ci = _chart(body, "top_locations_inventory")
    assert ci is not None
    assert {r["label"]: r["value"] for r in ci["series"][0]["data"]} == pytest.approx(want_i.to_dict())
    # the click-through lists items per location
    assert set(ch["drilldown"]) >= set(want.index)
    assert any("top consumption location" in s for s in body["insights"])


def test_consumption_page_still_works_without_the_column():
    s = copy.copy(STORE)
    s.consumption = STORE.consumption.drop(columns=["Store_Location"])
    s.inventory = STORE.inventory.drop(columns=["Store_Location"])
    app.dependency_overrides[get_store] = lambda: s
    try:
        r = client.get("/api/consumption")
        assert r.status_code == 200
        body = r.json()
        assert _chart(body, "top_locations_consumption") is None and _chart(body, "top_locations_inventory") is None
        assert not any("location" in x.lower() for x in body["insights"])
        assert body["kpis"] and body["charts"]            # the rest of the page is intact
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_chat_can_group_by_store_location(run):
    rs = run(measures=["consumption_value"], group_by=["store_location"])
    c = STORE.consumption
    want = c.groupby("Store_Location")["Value"].sum()
    got = rs.df.set_index("store_location")["consumption_value"]
    assert len(got) == len(want) == 120
    assert got.sum() == pytest.approx(want.sum())
    for k in list(want.index)[:10]:
        assert got[k] == pytest.approx(want[k])


def test_rca_offers_store_and_it_adds_up():
    a = rca_engine.analyze(STORE, Filters(), "consumption", "2026-03", "prior_month", [])
    assert a["reconciliation"]["ok"]
    assert any(d["key"] == "store" for d in a["dimensions"])
    opts = client.get("/api/rca/options").json()
    assert all(any(d["key"] == "store" for d in m["dims"]) for m in opts["metrics"] if m["key"] in ("consumption", "inventory_days"))
