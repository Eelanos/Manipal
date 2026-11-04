"""
Predictive Analysis must never show a number it cannot prove. These tests
recompute every formula a DIFFERENT way (plain pandas / day-by-day loops straight
from the raw tables) and compare, then check filters, edge cases, settings
validation, JSON safety and that all units (not just Pune/Goa) work.
"""

import json
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import DATA_END, DATA_START
from app.data_loader import DataStore, get_store
from app.filters import ALL, Filters
from app.main import app
from app.predict import engine
from app.predict import params as P

client = TestClient(app)
STORE = get_store()
# Position of each KPI card in the response (the page shows them in this order).
EXCESS, EXPIRY, DEMAND, ORDER, STOCKOUT = 0, 1, 2, 3, 4
NOSEAS = replace(P.default_params(), seasonality=False)


@pytest.fixture(autouse=True)
def _fresh():
    engine.clear_cache()
    yield


def _raw_rate(p, unit=None):
    plan = engine.compute_plan(STORE, Filters(unit=unit) if unit else Filters(), p)
    c = STORE.consumption
    w = c[(c.Date >= plan.win_start) & (c.Date <= plan.win_end)]
    if unit:
        w = w[w.Unit_ID == unit]
    return plan, w.groupby(["Unit_ID", "Item_ID"]).Qty.sum() / plan.window_days


# ---- 1. core formulas vs raw data ---------------------------------------------
def test_usage_cover_reorder_order_match_raw_pandas():
    p = NOSEAS
    plan, rate = _raw_rate(p)
    inv = STORE.inventory
    inv = inv[(inv.Date == plan.snapshot) & (inv.Expiry_Date > plan.snapshot)]      # expired stock is not usable
    inv = inv.groupby(["Unit_ID", "Item_ID"]).Stock_Qty.sum()
    # on order = the in-transit quantity recorded with the stock snapshot (all batch rows, expired or not)
    snap_rows = STORE.inventory[STORE.inventory.Date == plan.snapshot]
    po = snap_rows.groupby(["Unit_ID", "Item_ID"]).In_Transit_Qty.sum()
    L = plan.lines.set_index(["Unit_ID", "Item_ID"])
    assert len(L) > 0
    for key, r in L.iterrows():
        rt = float(rate.get(key, 0.0))
        oh, oo = float(inv.get(key, 0.0)), float(po.get(key, 0.0))
        assert r.rate == pytest.approx(rt)
        assert r.on_hand == pytest.approx(oh) and r.on_order == pytest.approx(oo)
        if r.status == P.STATUS_NO_RECORD:
            assert oh == 0 and r.order_qty == 0 and pd.isna(r.cover_days)      # data gap: not planned
        elif rt > 0:
            assert r.cover_days == pytest.approx(min(oh / rt, P.HORIZON_DAYS), abs=1e-6)
            rop = rt * (p.lead_days + p.buffer_days)
            assert r.reorder_point == pytest.approx(rop)
            up_to = math.ceil(rt * (p.lead_days + p.buffer_days + p.plan_days) - 1e-9)
            pos = oh + oo
            want = max(0.0, up_to - pos) if pos < rop else 0.0
            assert r.order_qty == pytest.approx(want, abs=1.0)
            assert r.order_value == pytest.approx(r.order_qty * STORE.items.set_index("Item_ID").Unit_Price[key[1]])
            exc = max(0.0, oh - rt * p.max_cover_days)
            assert r.excess_qty == pytest.approx(math.ceil(exc) if oh > 0 else 0.0, abs=1.0)


def test_status_rules_and_precedence():
    p = NOSEAS
    plan = engine.compute_plan(STORE, Filters(), p)
    for r in plan.lines.itertuples():
        if r.status == P.STATUS_NO_RECORD:
            assert r.rate > 0 and r.on_hand == 0 and r.order_qty == 0
        elif r.rate <= 0 and r.on_hand > 0:
            assert r.status == P.STATUS_NO_USAGE
        elif r.rate > 0 and r.position < r.reorder_point:
            crit = r.on_hand / r.rate < p.lead_days
            assert r.status == (P.STATUS_CRITICAL if crit else P.STATUS_ORDER_SOON)
            assert r.order_qty > 0
        elif r.excess_qty > 0:
            assert r.status == P.STATUS_EXCESS
        else:
            assert r.status == P.STATUS_HEALTHY and r.order_qty == 0
    assert set(plan.lines.status) <= set(P.STATUSES)


# ---- 2. seasonality -----------------------------------------------------------
def test_season_index_hand_check():
    idx = pd.date_range("2025-01-01", periods=24, freq="MS")
    vals = np.r_[np.arange(1, 13) * 10.0, np.arange(1, 13) * 20.0]    # year 2 is exactly double
    m = pd.Series(vals, index=idx)
    s = engine.season_index(m, 23)
    assert s.mean() == pytest.approx(1.0)
    # both years have the same shape, so the index equals the daily-rate shape of one year
    days = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], dtype=float)
    shape = (np.arange(1, 13) * 10 / days)
    shape = shape / shape.sum() * 12
    assert s == pytest.approx(shape)
    assert engine.season_index(m, 10) is None              # no complete year yet -> unavailable


def test_cover_days_match_day_by_day_simulation_with_seasonality():
    p = P.default_params()
    plan = engine.compute_plan(STORE, Filters(), p)
    assert plan.season_used
    factors = np.diff(plan.cum)
    sample = plan.lines[(plan.lines.rate > 0) & (plan.lines.on_hand > 0)].head(25)
    for r in sample.itertuples():
        left, d = r.on_hand, 0
        while left > 0 and d < len(factors):
            use = r.rate * factors[d]
            if use >= left:                         # fraction of the last day
                d += left / use
                left = 0
                break
            left -= use
            d += 1
        if r.cover_capped:
            assert d >= P.HORIZON_DAYS - 1
        else:
            assert r.cover_days == pytest.approx(d, abs=1e-6)


def test_toggle_seasonality_changes_numbers_but_not_structure():
    a = engine.compute_plan(STORE, Filters(), P.default_params())
    b = engine.compute_plan(STORE, Filters(), NOSEAS)
    assert len(a.lines) == len(b.lines)
    assert not np.allclose(a.lines.reorder_point, b.lines.reorder_point)


# ---- 3. expiry (independent FIFO loop) ----------------------------------------
def test_expiry_fifo_matches_loop():
    p = P.default_params()
    plan = engine.compute_plan(STORE, Filters(), p)
    cum = plan.cum
    b = plan.batches
    assert not b.empty
    rate = plan.lines.set_index(["Unit_ID", "Item_ID"]).rate
    total = 0.0
    for (u, i), g in b.groupby(["Unit_ID", "Item_ID"]):
        rt = float(rate.get((u, i), 0.0))
        claimed = 0.0
        for x in g.sort_values("days_to_expiry").itertuples():
            if x.days_to_expiry <= 0:
                assert x.risk_qty == pytest.approx(x.qty)       # expired = all at risk
                total += x.value
                continue
            d = min(x.days_to_expiry, len(cum) - 1)
            usable = rt * np.interp(d, np.arange(len(cum)), cum)
            used = min(max(usable - claimed, 0.0), x.qty)
            claimed += x.qty
            assert x.used_qty == pytest.approx(used)
            if x.days_to_expiry <= p.expiry_horizon_days:
                assert x.risk_qty == pytest.approx(x.qty - used)
            else:
                assert x.risk_qty == 0
            total += x.risk_value
    ov = engine.build_overview(STORE, Filters(), p)
    kpi = next(k for k in ov["kpis"] if k["label"] == "Expiry at risk")
    assert kpi["value"] == pytest.approx(total)


# ---- 4. forecast --------------------------------------------------------------
def test_forecast_shape_and_no_seasonality_formula():
    p = NOSEAS
    ov = engine.build_overview(STORE, Filters(), p)
    pts = ov["forecast"]["points"]
    fc = [x for x in pts if x["forecast"] is not None]
    assert len(fc) == P.FORECAST_MONTHS
    hist = [x for x in pts if x["actual"] is not None]
    assert len(hist) == P.HISTORY_MONTHS
    # no seasonality: forecast = window daily rate x days in month
    plan = engine.compute_plan(STORE, Filters(), p)
    c = STORE.consumption
    w = c[(c.Date >= plan.win_start) & (c.Date <= plan.win_end)]
    rate = w.Value.sum() / plan.window_days
    m0 = pd.Timestamp(fc[0]["month"] + "-01")
    assert fc[0]["forecast"] == pytest.approx(rate * m0.days_in_month, abs=1)
    for x in fc:
        if x["low"] is not None:
            assert x["low"] <= x["high"]


def test_forecast_origin_ignores_later_months():
    idx = pd.date_range("2025-01-01", periods=24, freq="MS")
    base = pd.Series(np.random.default_rng(1).uniform(50, 100, 24), index=idx)
    alt = base.copy()
    alt.iloc[18:] *= 10                                   # change only the "future" after origin 17
    a = engine._forecast_from(base, 17, 6, True, 3)
    b = engine._forecast_from(alt, 17, 6, True, 3)
    assert a == pytest.approx(b)


def test_backtest_range_needs_enough_samples():
    ov = engine.build_overview(STORE, Filters(), P.default_params())
    f = ov["forecast"]
    assert f["accuracy_pct"] is not None and 0 < f["accuracy_pct"] <= 100
    for x in f["points"]:
        if x["forecast"] is not None and f["range_available"]:
            assert x["low"] <= x["forecast"] * 1.0000001 and x["high"] >= x["forecast"] * 0.9999999


# ---- 5. filters ---------------------------------------------------------------
def test_unit_filter_narrows_and_department_only_changes_demand():
    p = P.default_params()
    all_ = engine.compute_plan(STORE, Filters(), p).lines
    one = engine.compute_plan(STORE, Filters(unit="H010"), p).lines
    assert set(one.Unit_ID) == {"H010"} and len(one) < len(all_)
    dept = STORE.departments[0]
    a = engine.build_overview(STORE, Filters(), p)
    b = engine.build_overview(STORE, Filters(department=dept), p)
    assert a["reorder"]["total"] == b["reorder"]["total"]            # planning ignores Department
    assert [k["value"] for i, k in enumerate(a["kpis"]) if i != DEMAND] == [k["value"] for i, k in enumerate(b["kpis"]) if i != DEMAND]
    assert b["kpis"][DEMAND]["value"] < a["kpis"][DEMAND]["value"]            # demand follows it
    assert b["department_note"] is True and a["department_note"] is False
    g = engine.compute_plan(STORE, Filters(stock_take_group="Pharmacy"), p).lines
    assert set(g.group) == {"Pharmacy"}


def test_groups_add_up_to_the_whole_when_seasonality_is_off():
    p = NOSEAS
    t = engine.build_overview(STORE, Filters(), p)
    parts = [engine.build_overview(STORE, Filters(stock_take_group=g), p) for g in ("Pharmacy", "General Store")]
    for i in (EXCESS, EXPIRY, ORDER, STOCKOUT):
        assert sum(x["kpis"][i]["value"] for x in parts) == pytest.approx(t["kpis"][i]["value"])


def test_period_filter_is_ignored():
    p = P.default_params()
    a = engine.build_overview(STORE, Filters(), p)
    b = engine.build_overview(STORE, Filters(date_from=pd.Timestamp("2026-01-01").date(), date_to=pd.Timestamp("2026-02-01").date()), p)
    assert a["kpis"] == b["kpis"]


# ---- 6. edge cases ------------------------------------------------------------
def test_empty_scope_is_graceful():
    ov = engine.build_overview(STORE, Filters(unit="NO_SUCH_UNIT"), P.default_params())
    assert ov["empty"] and ov["row_count"] == 0
    assert all(k["value"] == 0 for i, k in enumerate(ov["kpis"]) if i != DEMAND)
    assert ov["reorder"]["rows"] == [] and ov["insights"]
    json.dumps(ov, allow_nan=False)


def test_no_nan_in_any_payload():
    p = P.default_params()
    ov = engine.build_overview(STORE, Filters(), p)
    json.dumps(ov, allow_nan=False)
    row = ov["reorder"]["rows"][0]
    json.dumps(engine.build_item(STORE, Filters(), p, row["item_id"], row["unit_id"]), allow_nan=False)


def test_expired_stock_is_not_counted_as_usable():
    plan = engine.compute_plan(STORE, Filters(), P.default_params())
    inv = STORE.inventory[STORE.inventory.Date == plan.snapshot]
    exp = inv[inv.Expiry_Date <= plan.snapshot].groupby(["Unit_ID", "Item_ID"]).Stock_Qty.sum()
    assert len(exp) > 0
    L = plan.lines.set_index(["Unit_ID", "Item_ID"])
    for key, q in exp.items():
        assert L.loc[key, "expired_qty"] == pytest.approx(q)
    tot = inv.groupby(["Unit_ID", "Item_ID"]).Stock_Qty.sum()
    for key, r in L.iterrows():                     # usable + expired = everything on the shelf
        assert r.on_hand + r.expired_qty == pytest.approx(float(tot.get(key, 0.0)))
    # expired batches never reduce days of cover or create "excess"
    assert plan.batches[plan.batches.state == "expired"].risk_qty.sum() == pytest.approx(L.expired_qty.sum())


def test_usage_without_stock_record_is_not_planned_as_a_stockout():
    """The stock table has gaps: usage but no inventory row must NOT become a false Critical."""
    plan = engine.compute_plan(STORE, Filters(), P.default_params())
    L = plan.lines
    inv = STORE.inventory[STORE.inventory.Date == plan.snapshot]
    have = set(zip(inv.Unit_ID, inv.Item_ID))
    gap = L[np.array([(u, i) not in have for u, i in zip(L.Unit_ID, L.Item_ID)]) & (L.rate > 0).to_numpy()]
    assert len(gap) > 0
    assert (gap.status == P.STATUS_NO_RECORD).all() and (gap.order_qty == 0).all() and gap.cover_days.isna().all()
    crit = L[L.status == P.STATUS_CRITICAL]
    assert all((u, i) in have for u, i in zip(crit.Unit_ID, crit.Item_ID))   # every Critical has a real stock row
    ov = engine.build_overview(STORE, Filters(), P.default_params())
    assert any("no stock record" in n for n in ov["notes"])


def test_cover_chart_rows_sorted_with_tiebreak_and_order_info():
    ov = engine.build_overview(STORE, Filters(), P.default_params())
    rows = ov["cover"]["rows"]
    assert 0 < len(rows) <= P.TOP_COVER_ROWS
    covers = [r["cover_days"] for r in rows]
    assert covers == sorted(covers)
    plan = engine.compute_plan(STORE, Filters(), P.default_params()).lines.set_index(["Unit_ID", "Item_ID"])
    zero = [r for r in rows if r["cover_days"] == 0]
    pos_cover = [plan.loc[(r["unit_id"], r["item_id"]), "position_cover_days"] for r in zero]
    assert pos_cover == sorted(pos_cover)                     # least-covered (incl. open orders) first
    assert all(r["on_order"] == plan.loc[(r["unit_id"], r["item_id"]), "on_order"] for r in rows)


def test_open_orders_reduce_the_order():
    p = NOSEAS
    plan = engine.compute_plan(STORE, Filters(), p)
    L = plan.lines
    withpo = L[(L.on_order > 0) & (L.rate > 0)]
    for r in withpo.itertuples():
        assert r.position == pytest.approx(r.on_hand + r.on_order)
        if r.order_qty > 0:
            assert r.order_qty == pytest.approx(max(0.0, r.order_up_to - r.position))


# ---- 7. item drill-down -------------------------------------------------------
def test_item_matches_overview_row_and_projection_is_consistent():
    p = P.default_params()
    ov = engine.build_overview(STORE, Filters(), p)
    row = ov["reorder"]["rows"][0]
    it = engine.build_item(STORE, Filters(), p, row["item_id"], row["unit_id"])
    for k_item, k_row in [("on_hand", "on_hand"), ("daily_usage", "daily_usage"), ("order_qty", "order_qty"),
                          ("reorder_point", "reorder_point"), ("cover_days", "cover_days")]:
        assert it["facts"][k_item] == row[k_row]
    proj = it["projection"]
    assert proj[0]["day"] == 0 and all(x["stock"] >= 0 for x in proj)
    assert it["facts"]["order_by"] is not None
    with pytest.raises(engine.PredictError):
        engine.build_item(STORE, Filters(), p, "NOPE", "H010")


def test_item_stock_projection_matches_simulation():
    p = NOSEAS
    plan = engine.compute_plan(STORE, Filters(), p)
    r = plan.lines[(plan.lines.rate > 0) & (plan.lines.on_hand > 0)].iloc[0]
    it = engine.build_item(STORE, Filters(), p, r.Item_ID, r.Unit_ID)
    for x in it["projection"][:40]:
        arrive = r.on_order if x["day"] >= p.lead_days else 0
        assert x["stock"] == pytest.approx(max(0, r.on_hand + arrive - r.rate * x["day"]), abs=1)


# ---- 8. API -------------------------------------------------------------------
def test_options_publish_the_same_spec():
    o = client.get("/api/predict/options").json()
    assert {s["key"] for s in o["settings"]} == set(P.SETTINGS)
    for s in o["settings"]:
        assert s["default"] == P.SETTINGS[s["key"]].default
    assert o["units"] and o["statuses"]


def test_api_validation_and_defaults():
    assert client.get("/api/predict/overview").status_code == 200
    assert client.get("/api/predict/overview?lead_days=0").status_code == 400
    assert client.get("/api/predict/overview?window_months=5").status_code == 400
    assert client.get("/api/predict/overview?plan_days=9999").status_code == 400
    assert client.get("/api/predict/overview?seasonality=false&lead_days=14").json()["settings"]["lead_days"] == 14
    assert client.get("/api/predict/item?item_id=NOPE&unit_id=H010").status_code == 404
    r = client.get("/api/predict/overview?unit=H010&stock_take_group=Pharmacy").json()
    assert r["scope"] == "H010" and all(x["unit_id"] == "H010" for x in r["reorder"]["rows"])


def test_every_setting_moves_the_right_numbers():
    base = engine.build_overview(STORE, Filters(), P.default_params())
    longer = engine.build_overview(STORE, Filters(), replace(P.default_params(), lead_days=30))
    assert longer["kpis"][ORDER]["value"] >= base["kpis"][ORDER]["value"]          # more lines need ordering
    bigger_cover = engine.build_overview(STORE, Filters(), replace(P.default_params(), max_cover_days=365))
    assert bigger_cover["kpis"][EXCESS]["value"] == base["kpis"][EXCESS]["value"]    # inventory value does not depend on settings
    assert bigger_cover["kpis"][EXCESS]["note"] != base["kpis"][EXCESS]["note"]       # but the excess quoted under it does
    assert (engine.compute_plan(STORE, Filters(), replace(P.default_params(), max_cover_days=365)).lines["excess_value"].sum()
            <= engine.compute_plan(STORE, Filters(), P.default_params()).lines["excess_value"].sum())    # less counted as excess
    longer_window = engine.build_overview(STORE, Filters(), replace(P.default_params(), window_months=12))
    assert longer_window["settings"]["window_months"] == 12


# ---- 9. all units, nothing hardcoded ------------------------------------------
def test_works_for_all_units_not_just_pune_and_goa(monkeypatch):
    import app.data_loader as dl
    every = pd.read_parquet(dl.PARQUET_DIR / "Unit_Master.parquet")["Unit_ID"].tolist()
    assert len(every) > 2
    monkeypatch.setattr(dl, "ACTIVE_UNITS", ["H010", "H011"])           # the old two-unit demo scope
    two = DataStore()
    monkeypatch.setattr(dl, "ACTIVE_UNITS", every)
    full = DataStore()
    p = P.default_params()
    ov = engine.build_overview(full, Filters(), p)
    units = {r["unit_id"] for r in ov["reorder"]["rows"] + ov["excess"]["rows"]}
    assert len(units) > 2 and ov["row_count"] > engine.build_overview(two, Filters(), p)["row_count"]
    assert {u["Unit_ID"] for u in full.unit_options} == set(every)
    one = engine.build_overview(full, Filters(unit=every[-1]), p)
    assert one["scope"] == every[-1] and one["row_count"] > 0
    json.dumps(ov, allow_nan=False)


def test_status_drilldown_matches_donut_and_rows():
    """Every donut slice's list has exactly the slice's line count / stock value, and only that status."""
    ov = client.get("/api/predict/overview").json()
    for h in ov["health"]:
        d = client.get("/api/predict/status", params={"status": h["status"]}).json()
        assert d["total"] == h["lines"] and len(d["rows"]) == min(d["total"], P.MAX_TABLE_ROWS)
        assert d["more"] == (d["total"] > P.MAX_TABLE_ROWS)
        assert all(r["status"] == h["status"] for r in d["rows"])
        assert abs(d["stock_value"] - h["stock_value"]) <= 1
        assert h["rule"] and d["rule"] == h["rule"]
    assert client.get("/api/predict/status", params={"status": "Nope"}).status_code == 404


def test_kpi_cards_come_in_the_page_order_and_default_delivery_is_two_days():
    ov = client.get("/api/predict/overview").json()
    labels = [k["label"] for k in ov["kpis"]]
    assert labels[EXCESS].startswith("Inventory,") and labels[EXPIRY] == "Expiry at risk"
    assert labels[DEMAND].startswith("Demand") and labels[ORDER] == "Items to order now" and labels[STOCKOUT] == "Stock-out risk"
    assert ov["settings"]["lead_days"] == 2 == P.default_params().lead_days
    assert ov["kpis"][STOCKOUT]["note"] == "Out of stock within 2 days"
    # the stock-out count is exactly the Critical status, which is "usable stock lasts under the delivery time"
    assert ov["kpis"][STOCKOUT]["value"] == next(h["lines"] for h in ov["health"] if h["status"] == P.STATUS_CRITICAL)


# ---- where "on order" comes from -------------------------------------------------
def test_on_order_default_is_stock_in_transit_and_matches_inventory_page():
    plan = engine.compute_plan(STORE, Filters(), P.default_params())
    snap = STORE.inventory[STORE.inventory.Date == plan.snapshot]
    assert P.ON_ORDER_SOURCE == "inventory" and engine.on_order_source(STORE) == "inventory"
    assert plan.lines["on_order"].sum() == pytest.approx(float(snap.In_Transit_Qty.sum()))
    assert plan.lines["on_order"].sum() > 0
    # same quantity the Inventory Analysis dashboard values as "in transit" (it sums In_Transit_Value)
    assert snap.In_Transit_Value.sum() > 0
    assert any("stock in transit" in n for n in engine.build_overview(STORE, Filters(), P.default_params())["notes"])


def test_purchase_source_ignores_stale_in_transit_orders(monkeypatch):
    """Purchase-order mode: an order still In-Transit for far longer than OPEN_PO_MAX_AGE_DAYS must not count."""
    monkeypatch.setattr(P, "ON_ORDER_SOURCE", "purchase")
    engine.clear_cache()
    assert engine.on_order_source(STORE) == "purchase"
    plan = engine.compute_plan(STORE, Filters(), P.default_params())
    snap = plan.snapshot
    po = STORE.purchase
    po = po[(po.Status == P.OPEN_PO_STATUS) & (po.PO_Date <= snap)
            & (po.PO_Date >= pd.Timestamp(DATA_START)) & (po.PO_Date <= pd.Timestamp(DATA_END))]
    fresh = po[po.PO_Date >= snap - pd.Timedelta(days=P.OPEN_PO_MAX_AGE_DAYS)]
    assert plan.lines["on_order"].sum() == pytest.approx(float(fresh.Qty.sum()))
    # lifting the age limit counts them: the rule, and only the rule, removes them
    monkeypatch.setattr(P, "OPEN_PO_MAX_AGE_DAYS", 100000)
    engine.clear_cache()
    plan_all = engine.compute_plan(STORE, Filters(), P.default_params())
    assert plan_all.lines["on_order"].sum() == pytest.approx(float(po.Qty.sum()))
    assert any("purchase orders" in n for n in engine.build_overview(STORE, Filters(), P.default_params())["notes"])


def test_missing_in_transit_column_falls_back_to_purchase_orders():
    class NoTransit:
        inventory = STORE.inventory.drop(columns=["In_Transit_Qty"])
    assert engine.on_order_source(NoTransit()) == "purchase"


def test_inventory_value_card_matches_snapshot_and_quotes_excess():
    """First card = total stock value on the snapshot date; the excess value is written under it."""
    snap = engine.compute_plan(STORE, Filters(), P.default_params()).snapshot
    for f in (Filters(), Filters(stock_take_group="Pharmacy")):
        k = engine.build_overview(STORE, f, P.default_params())["kpis"][EXCESS]
        raw = STORE.inventory[STORE.inventory["Date"] == snap]
        if f.stock_take_group != "All":
            raw = raw[raw["Stock Take Group"] == f.stock_take_group]
        assert k["label"] == f"Inventory, {snap:%d %b %Y}"
        assert k["value"] == pytest.approx(float(raw["Stock_Value"].sum()), rel=1e-9)
        exc = engine.compute_plan(STORE, f, P.default_params()).lines["excess_value"].sum()
        assert k["note"] == "Excess stock value " + engine.inr_compact(float(exc)).replace(" ", "\u00a0")
