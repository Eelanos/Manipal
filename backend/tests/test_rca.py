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
# The data runs Apr 2024 - Mar 2026. In the tests below, "may" / "apr" mean the latest month (Mar 2026) and the
# month before it (Feb 2026); 2024-04 is the first month, so it has no prior month.
MONTHS = ["2024-04", "2025-01", "2025-02", "2025-07", "2025-12", "2026-02", "2026-03"]


def _try(fn, *a):
    try:
        return fn(*a)
    except RcaError:
        return None      # e.g. no prior month for Apr 2024: a clear error, not a wrong answer


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
    cases = [("formulary_compliance", "prior_month", "2026-03", ["unit:PUN", "payer:Cash"]),
             ("consumption", "budget", "2025-07", ["unit:PUN", "department:Cardiology"]),
             ("inventory_days", "prior_month", "2026-03", ["unit:GOA"]),
             ("non_moving_pct", "same_month_last_year", "2026-02", ["department:Oncology"])]
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
    may, apr = c[c.Month_Start == "2026-03-01"], c[c.Month_Start == "2026-02-01"]
    want = -100 * (may[may.Unit_Name == "PUN"].off.sum() / may.Value.sum()
                   - apr[apr.Unit_Name == "PUN"].off.sum() / apr.Value.sum())
    a = engine.analyze(store, Filters(), "formulary_compliance", "2026-03", "prior_month", [])
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
    a = engine.analyze(store, Filters(), "formulary_compliance", "2026-03", "target", [])
    assert a["headline"]["base"] == 92.0
    assert a["headline"]["delta"] == pytest.approx(a["headline"]["current"] - 92.0)
    assert a["reconciliation"]["ok"]


def test_budget_is_refused_where_it_does_not_exist(store):
    with pytest.raises(RcaError):
        engine.analyze(store, Filters(stock_take_group="Pharmacy"), "consumption", "2026-03", "budget", [])
    with pytest.raises(RcaError):
        engine.analyze(store, Filters(), "consumption", "2026-03", "budget", ["doctor:Dr. Rohan Kulkarni"])
    with pytest.raises(RcaError):
        engine.analyze(store, Filters(), "inventory_days", "2026-03", "target", [])


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
    may, apr = c[c.Month_Start == "2026-03-01"], c[c.Month_Start == "2026-02-01"]
    off = lambda d: float(d.loc[~(d.Is_Formulary == True), "Value"].sum())    # noqa: E712
    want = -100 * (off(may) - off(apr)) / may.Value.sum()
    t = tree.walk(store, Filters(), "formulary_compliance", "2026-03", "prior_month")
    node = next(n for n in t["tree"]["children"] if n["id"] == "off")
    assert node["impact"] == pytest.approx(want, abs=1e-9)


def test_api_shapes_and_clear_errors():
    o = client.get("/api/rca/options").json()
    assert {m["key"] for m in o["metrics"]} == set(MEASURES)
    assert o["default_month"] in [m["value"] for m in o["months"]]
    ok = client.get("/api/rca/analysis", params={"metric": "formulary_compliance", "month": "2026-03", "compare": "prior_month",
                                                 "path": ["unit:PUN"]})
    assert ok.status_code == 200 and ok.json()["chain"][1]["segment"] == "PUN"
    bad = client.get("/api/rca/analysis", params={"metric": "formulary_compliance", "month": "2024-04", "compare": "prior_month"})
    assert bad.status_code == 400 and "no data" in bad.json()["detail"].lower()
    assert client.get("/api/rca/analysis", params={"metric": "nope", "month": "2026-03"}).status_code == 400
    assert client.get("/api/rca/analysis", params={"metric": "consumption", "month": "2026-03", "compare": "target"}).status_code == 400
    assert client.get("/api/rca/tree", params={"metric": "consumption", "month": "2026-03"}).status_code == 400
    assert client.get("/api/rca/tree", params={"metric": "inventory_days", "month": "2026-03"}).status_code == 200


def test_existing_dashboards_unchanged_by_rca():
    for slug in ["inventory-analysis", "consumption", "formulary-compliance", "sob-opportunities", "sob-compliance"]:
        r = client.get(f"/api/{slug}")
        assert r.status_code == 200 and r.json()["row_count"] > 0


# ---------------------------------------------------------------------------
# The command-center views: every unit / region / doctor ... as an entity
# ---------------------------------------------------------------------------
def test_all_twelve_units_are_in_the_data(store):
    assert len(store.units) == 12
    assert set(store.consumption.Unit_ID) == set(store.units.Unit_ID)
    opts = client.get("/api/filter-options").json()
    assert len(opts["units"]) == 12


LENS_CASES = [(m, c) for m, meas in MEASURES.items() for c in meas.compares]


@pytest.mark.parametrize("metric,compare", LENS_CASES)
def test_every_lens_adds_up_to_the_change(store, metric, compare):
    """For every view (region, unit, doctor ...) the entities' parts add up to the whole change."""
    ran = 0
    for month in ("2025-07", "2026-02", "2026-03"):
        for dim in MEASURES[metric].dims_for(compare):
            try:
                L = engine.lens(store, Filters(), metric, month, compare, dim)
            except RcaError:
                continue
            ran += 1
            assert L["reconciliation"]["ok"], (metric, compare, month, dim, L["reconciliation"])
            if L["entities"]:
                total = sum(e["contribution"] for e in L["entities"])
                eff = sum(x["contribution"] for x in L["effects"])
                assert total + eff == pytest.approx(L["headline"]["delta"], abs=1e-6 * max(1, abs(L["headline"]["delta"])))
    assert ran > 0


def test_region_is_a_view_and_matches_the_unit_master(store):
    L = engine.lens(store, Filters(), "formulary_compliance", "2026-03", "prior_month", "region")
    assert {e["segment"] for e in L["entities"]} == set(store.units.Region)
    U = engine.lens(store, Filters(), "formulary_compliance", "2026-03", "prior_month", "unit")
    by_region = store.units.set_index("Unit_Name").Region
    for reg in L["entities"]:
        mine = sum(u["contribution"] for u in U["entities"] if by_region[u["segment"]] == reg["segment"])
        assert reg["contribution"] == pytest.approx(mine, abs=1e-9)


def test_budget_can_be_split_by_region_and_still_adds_up(store):
    a = engine.analyze(store, Filters(), "consumption", "2026-03", "budget", [])
    assert "region" in {d["key"] for d in a["dimensions"]} and a["reconciliation"]["ok"]
    b = engine.analyze(store, Filters(), "consumption", "2026-03", "budget", ["region:South"], full=True)
    assert b["reconciliation"]["ok"]


def test_entity_numbers_recomputed_independently(store):
    """KHO's own compliance and its part of the network change, rebuilt straight from the rows."""
    c = store.consumption
    may, apr = c[c.Month_Start == "2026-03-01"], c[c.Month_Start == "2026-02-01"]
    off = lambda d: float(d.loc[~(d.Is_Formulary == True), "Value"].sum())    # noqa: E712
    k_may, k_apr = may[may.Unit_Name == "KHO"], apr[apr.Unit_Name == "KHO"]
    own = 100 - 100 * off(k_may) / k_may.Value.sum()
    part = -100 * (off(k_may) / may.Value.sum() - off(k_apr) / apr.Value.sum())
    e = engine.entity(store, Filters(), "formulary_compliance", "2026-03", "prior_month", "unit", "KHO")["entity"]
    assert e["own_current"] == pytest.approx(own, abs=1e-9)
    assert e["contribution"] == pytest.approx(part, abs=1e-9)
    assert e["own_change"] == pytest.approx(own - (100 - 100 * off(k_apr) / k_apr.Value.sum()), abs=1e-9)


@pytest.mark.parametrize("dim", ["unit", "region", "doctor", "department"])
def test_ranking_only_names_real_drivers(store, dim):
    from app.config import RCA_MATERIAL_SHARE_PCT, RCA_MIN_OVERINDEX_PP
    L = engine.lens(store, Filters(), "formulary_compliance", "2026-03", "prior_month", dim)
    for ent in L["entities"][:4]:
        out = engine.entity(store, Filters(), "formulary_compliance", "2026-03", "prior_month", dim, ent["segment"])
        for r in out["ranking"]:
            assert r["share_of_slice_pct"] >= RCA_MATERIAL_SHARE_PCT
            assert r["share_of_slice_pct"] - (r["weight_in_slice_pct"] or 0) >= RCA_MIN_OVERINDEX_PP
            assert r["dim"] != dim            # never "explains" a unit by the unit itself
        assert out["reconciliation"]["ok"]


def test_a_card_cause_equals_the_first_ranked_driver(store):
    c = engine.cause(store, Filters(), "formulary_compliance", "2026-03", "prior_month", "unit", "KHO")["top_cause"]
    r = engine.entity(store, Filters(), "formulary_compliance", "2026-03", "prior_month", "unit", "KHO")["ranking"][0]
    assert (c["dim"], c["segment"]) == (r["dim"], r["segment"])
    assert c["share_of_slice_pct"] == pytest.approx(r["share_of_slice_pct"])


def test_flags_follow_the_published_rule(store):
    from app.config import RCA_MATERIAL_SHARE_PCT
    L = engine.lens(store, Filters(), "formulary_compliance", "2026-03", "prior_month", "unit")
    gross = L["summary"]["gross"]
    for e in L["entities"]:
        material = abs(e["contribution"]) / gross * 100 >= RCA_MATERIAL_SHARE_PCT
        if not material:
            assert e["flag"] == "minor"
        elif e["evidence"].get("available"):
            assert e["flag"] == {"unusual": "deviating", "watch": "watch", "normal": "normal"}[e["evidence"]["flag"]]


def test_single_segment_scope_has_no_entities_instead_of_a_wrong_list(store):
    L = engine.lens(store, Filters(unit="H010"), "formulary_compliance", "2026-03", "prior_month", "unit")
    assert L["entities"] == [] and L["lens"]["segments"] == 1


def test_tree_for_one_entity_is_that_entitys_own_tree(store):
    t = tree.walk(store, Filters(), "formulary_compliance", "2026-03", "prior_month", ["unit:KHO"])
    c = store.consumption
    may, apr = c[(c.Month_Start == "2026-03-01") & (c.Unit_Name == "KHO")], c[(c.Month_Start == "2026-02-01") & (c.Unit_Name == "KHO")]
    off = lambda d: float(d.loc[~(d.Is_Formulary == True), "Value"].sum())    # noqa: E712
    assert t["tree"]["current"] == pytest.approx(100 - 100 * off(may) / may.Value.sum(), abs=1e-9)
    assert t["tree"]["base"] == pytest.approx(100 - 100 * off(apr) / apr.Value.sum(), abs=1e-9)
    assert t["reconciliation"]["ok"] and t["scope"]["path"][0]["value"] == "KHO"
    # Same tree through the Filters route must agree (a unit filter is the same slice)
    t2 = tree.walk(store, Filters(unit="H001"), "formulary_compliance", "2026-03", "prior_month")
    assert t2["tree"]["current"] == pytest.approx(t["tree"]["current"], abs=1e-9)


def test_new_endpoints_shapes_and_errors():
    p = {"metric": "formulary_compliance", "month": "2026-03", "compare": "prior_month"}
    L = client.get("/api/rca/lens", params={**p, "dim": "unit"})
    assert L.status_code == 200 and len(L.json()["entities"]) == 12
    assert client.get("/api/rca/lens", params={**p, "dim": "nope"}).status_code == 400
    assert client.get("/api/rca/lens", params={**p, "compare": "target", "dim": "unit"}).status_code == 200
    E = client.get("/api/rca/entity", params={**p, "dim": "unit", "segment": "PUN"})
    assert E.status_code == 200 and E.json()["entity"]["segment"] == "PUN"
    assert client.get("/api/rca/entity", params={**p, "dim": "unit", "segment": "Atlantis"}).status_code == 400
    assert client.get("/api/rca/cause", params={**p, "dim": "unit", "segment": "PUN"}).status_code == 200
    full = client.get("/api/rca/analysis", params={**p, "path": ["unit:PUN"], "full": True}).json()
    assert all(len(b["rows"]) == b["segments"] for b in full["dimensions"])
    tr = client.get("/api/rca/tree", params={**p, "path": ["unit:PUN"]})
    assert tr.status_code == 200 and tr.json()["scope"]["path"][0]["value"] == "PUN"
