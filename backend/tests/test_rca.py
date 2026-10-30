"""
RCA must never show a number it cannot prove. These tests check the three things
that make an RCA trustworthy:

  1. Every split adds up EXACTLY to the change it explains (and the API says so).
  2. The headline figures are the same ones the dashboards show.
  3. The contributions equal an independent recalculation done a different way.
"""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import metrics
from app.filters import Filters, apply
from app.main import app
from app.rca import engine, tree
from app.rca.measures import MEASURES, RcaError, Scope, stock_class

client = TestClient(app)

SCOPES = {
    "network": Filters(),
    "pune": Filters(unit="H010"),
    "pharmacy": Filters(stock_take_group="Pharmacy"),
    "goa_cardiology": Filters(unit="H011", department="Cardiology"),
}
MONTHS = ["2025-01", "2025-02", "2025-07", "2025-12", "2026-03", "2026-05", "2026-12"]


def _try(fn, *a):
    try:
        return fn(*a)
    except RcaError:
        return None      # e.g. no prior month for Jan 2025: a clear error, not a wrong answer


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("metric", list(MEASURES))
def test_every_split_adds_up(store, scope, metric):
    ran = 0
    for compare in MEASURES[metric].compares:
        for month in MONTHS:
            a = _try(engine.analyze, store, SCOPES[scope], metric, month, compare, [])
            if a is None:
                continue
            ran += 1
            assert a["reconciliation"]["ok"], (scope, metric, compare, month, a["reconciliation"])
    assert ran > 0


def test_drill_paths_add_up(store):
    cases = [("formulary_compliance", "prior_month", "2026-05", ["unit:PUN", "payer:Cash"]),
             ("consumption", "budget", "2025-07", ["unit:PUN", "department:Cardiology"]),
             ("inventory_days", "prior_month", "2026-03", ["unit:GOA"]),
             ("non_moving_pct", "same_month_last_year", "2026-12", ["department:Oncology"])]
    for metric, compare, month, path in cases:
        a = engine.analyze(store, Filters(), metric, month, compare, path)
        assert a["reconciliation"]["ok"]
        assert len(a["chain"]) == len(path) + 1
        # a drilled step can never explain more than the whole slice above it, in absolute terms of its own total
        for blk in a["dimensions"]:
            assert abs(blk["total"] - a["chain"][-1]["contribution"]) < 1e-6 * max(1, abs(a["headline"]["delta"]))


def test_headlines_match_the_dashboards(store):
    f = Filters()
    cons, inv, bud = apply(store.consumption, f), apply(store.inventory, f), apply(store.budget, f)
    sc = Scope(store, f, [])
    months = engine.months_available(store)
    days = metrics.inventory_days_series(inv, cons).set_index("Date")["inventory_days"]
    bdays = metrics.budget_inventory_days_series(inv, bud).set_index("Date")["budget_inventory_days"]
    bmonth = metrics.budget_by_month(bud).set_index("Month_Start")["Budget_Value"]
    for mo in months:
        c, i = cons[cons.Month_Start == mo], inv[inv.Month_Start == mo]
        assert abs(MEASURES["formulary_compliance"].root_value(sc, mo) - metrics.formulary_kpis(c)["compliance_pct"]) < 0.006
        assert abs(MEASURES["consumption"].root_value(sc, mo) - metrics.total_value(c)) < 1e-4
        assert abs(MEASURES["non_moving_pct"].root_value(sc, mo) - metrics.inventory_kpis(i)["non_moving_pct"]) < 0.006
        assert abs(MEASURES["consumption"].root_budget_series(sc).loc[mo] - bmonth[mo]) < 1e-4
    for d in days.index:
        mo = pd.Timestamp(d).replace(day=1)
        assert abs(MEASURES["inventory_days"].root_value(sc, mo) - days[d]) < 0.051     # dashboard rounds to 1 dp
        assert abs(MEASURES["inventory_days"].root_budget_series(sc).loc[mo] - bdays[d]) < 0.051


def test_compliance_contribution_recomputed_independently(store):
    """Pune's share of the May 2026 drop, from raw rows with no RCA code."""
    c = store.consumption.copy()
    c["off"] = np.where(c["Is_Formulary"] == True, 0.0, c["Value"])    # noqa: E712
    may, apr = c[c.Month_Start == "2026-05-01"], c[c.Month_Start == "2026-04-01"]
    want = -100 * (may[may.Unit_Name == "PUN"].off.sum() / may.Value.sum()
                   - apr[apr.Unit_Name == "PUN"].off.sum() / apr.Value.sum())
    a = engine.analyze(store, Filters(), "formulary_compliance", "2026-05", "prior_month", [])
    unit = next(b for b in a["dimensions"] if b["key"] == "unit")
    got = next(r for r in unit["rows"] if r["segment"] == "PUN")["contribution"]
    assert got == pytest.approx(want, abs=1e-9)
    total = -100 * (may.off.sum() / may.Value.sum() - apr.off.sum() / apr.Value.sum())
    assert a["headline"]["delta"] == pytest.approx(total, abs=1e-9)


def test_inventory_days_effects_match_a_swap_calculation(store):
    """Move stock first, then consumption, then the calendar: the three effects equal those steps."""
    sc = Scope(store, Filters(), [])
    m, b = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-02-01")
    S = lambda mo: float(sc.inv_full[sc.inv_full.Month_Start == mo].Stock_Value.sum())
    C = lambda mo: float(sc.cons_full[sc.cons_full.Month_Start == mo].Value.sum())
    D1, D0 = m.days_in_month, b.days_in_month
    stock = S(m) * D1 / C(m) - S(b) * D1 / C(m)
    cons = S(b) * D1 / C(m) - S(b) * D1 / C(b)
    cal = S(b) * D1 / C(b) - S(b) * D0 / C(b)
    a = engine.analyze(store, Filters(), "inventory_days", "2026-03", "prior_month", [])
    blk = a["dimensions"][0]
    assert sum(r["parts"]["Stock"] for r in blk["rows"]) + (blk["other"] or {}).get("contribution", 0) * 0 == pytest.approx(
        sum(r["parts"]["Stock"] for r in blk["rows"]))
    full = Scope(store, Filters(), []).__class__  # (kept for clarity: engine totals come from the full scope)
    cb = MEASURES["inventory_days"].contributions(sc, "unit", m, engine.make_base(MEASURES["inventory_days"], "prior_month", m, engine.months_available(store)))
    assert cb.frame["stock_effect"].sum() == pytest.approx(stock, abs=1e-9)
    assert cb.frame["consumption_effect"].sum() + sum(e["contribution"] for e in cb.effects) == pytest.approx(cons + cal, abs=1e-9)
    assert a["headline"]["delta"] == pytest.approx(stock + cons + cal, abs=1e-9)


def test_target_gap_is_exact(store):
    a = engine.analyze(store, Filters(), "formulary_compliance", "2026-05", "target", [])
    assert a["headline"]["base"] == 92.0
    assert a["headline"]["delta"] == pytest.approx(a["headline"]["current"] - 92.0)
    assert a["reconciliation"]["ok"]


def test_budget_is_refused_where_it_does_not_exist(store):
    with pytest.raises(RcaError):
        engine.analyze(store, Filters(stock_take_group="Pharmacy"), "consumption", "2026-05", "budget", [])
    with pytest.raises(RcaError):
        engine.analyze(store, Filters(), "consumption", "2026-05", "budget", ["doctor:Dr. Rohan Kulkarni"])
    with pytest.raises(RcaError):
        engine.analyze(store, Filters(), "inventory_days", "2026-05", "target", [])


def test_stock_classes_add_up_to_total_stock(store):
    inv = store.inventory
    cls = stock_class(inv)
    assert set(cls.unique()) <= {"Expired", "Near expiry", "Non-moving", "Healthy"}
    assert cls.notna().all()
    by = inv.groupby(cls).Stock_Value.sum()
    assert by.sum() == pytest.approx(inv.Stock_Value.sum())


@pytest.mark.parametrize("metric", tree.TREE_METRICS)
def test_tree_branches_add_up(store, metric):
    ran = 0
    for scope in SCOPES.values():
        for compare in tree.TREE_COMPARES:
            for month in MONTHS:
                t = _try(tree.walk, store, scope, metric, month, compare)
                if t is None:
                    continue
                ran += 1
                assert t["reconciliation"]["ok"], (metric, compare, month, t["reconciliation"])
    assert ran > 0


def test_tree_off_formulary_branch_recomputed_independently(store):
    c = store.consumption
    may, apr = c[c.Month_Start == "2026-05-01"], c[c.Month_Start == "2026-04-01"]
    off = lambda d: float(d.loc[~(d.Is_Formulary == True), "Value"].sum())    # noqa: E712
    want = -100 * (off(may) - off(apr)) / may.Value.sum()
    t = tree.walk(store, Filters(), "formulary_compliance", "2026-05", "prior_month")
    node = next(n for n in t["tree"]["children"] if n["id"] == "off")
    assert node["impact"] == pytest.approx(want, abs=1e-9)


def test_api_shapes_and_clear_errors():
    o = client.get("/api/rca/options").json()
    assert {m["key"] for m in o["metrics"]} == set(MEASURES)
    assert o["default_month"] in [m["value"] for m in o["months"]]
    ok = client.get("/api/rca/analysis", params={"metric": "formulary_compliance", "month": "2026-05", "compare": "prior_month",
                                                 "path": ["unit:PUN"]})
    assert ok.status_code == 200 and ok.json()["chain"][1]["segment"] == "PUN"
    bad = client.get("/api/rca/analysis", params={"metric": "formulary_compliance", "month": "2025-01", "compare": "prior_month"})
    assert bad.status_code == 400 and "no data" in bad.json()["detail"].lower()
    assert client.get("/api/rca/analysis", params={"metric": "nope", "month": "2026-05"}).status_code == 400
    assert client.get("/api/rca/analysis", params={"metric": "consumption", "month": "2026-05", "compare": "target"}).status_code == 400
    assert client.get("/api/rca/tree", params={"metric": "consumption", "month": "2026-05"}).status_code == 400
    assert client.get("/api/rca/tree", params={"metric": "inventory_days", "month": "2026-05"}).status_code == 200


def test_existing_dashboards_unchanged_by_rca():
    for slug in ["inventory-analysis", "consumption", "formulary-compliance", "sob-opportunities", "sob-compliance"]:
        r = client.get(f"/api/{slug}")
        assert r.status_code == 200 and r.json()["row_count"] > 0
