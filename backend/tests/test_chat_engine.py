"""Executor, resolver and time-handling edge cases, each checked against independent pandas."""

import numpy as np
import pandas as pd
import pytest

from app.chat.resolver import match_value, resolve_query
from app.chat.spec import FilterSpec, TimeSpec
from app.chat.timeparse import PlanError, previous_period
from conftest import make_spec


# -- stock is never summed across snapshots ---------------------------------------------------
def test_stock_uses_latest_snapshot_not_a_sum(store, run):
    inv = store.inventory
    last = inv["Date"].max()
    expect = inv.loc[inv["Date"] == last, "Stock_Value"].sum()
    rs = run(measures=["stock_value"])
    assert rs.totals["stock_value"] == pytest.approx(expect)


def test_stock_by_month_equals_each_snapshot(store, run, cat):
    rs = run(measures=["stock_value"], time_grain="month")
    df = rs.df
    assert len(df) == len(cat.tables["inventory"].snapshot_dates)
    # the monthly values are a series of distinct snapshots, not cumulative
    assert df["stock_value"].max() < 3 * df["stock_value"].median()


# -- ratios and additivity ---------------------------------------------------------------------
def test_ratio_is_weighted_not_averaged(store, run):
    by_dept = run(measures=["formulary_compliance_pct"], group_by=["department"])
    c = store.consumption
    for _, row in by_dept.df.iterrows():
        sub = c[c["Dept_Name"] == row["department"]]
        want = sub.loc[sub["Is_Formulary"], "Value"].sum() / sub["Value"].sum() * 100
        assert row["formulary_compliance_pct"] == pytest.approx(want, abs=0.01)
    naive = by_dept.df["formulary_compliance_pct"].mean()
    assert by_dept.totals["formulary_compliance_pct"] != pytest.approx(naive, abs=1e-9)


def test_additive_groups_sum_to_total(run):
    rs = run(measures=["consumption_value"], group_by=["department"])
    assert rs.df["consumption_value"].sum() == pytest.approx(rs.totals["consumption_value"])
    rs = run(measures=["consumption_value"], group_by=["payer_type"], time_grain="quarter")
    assert rs.df["consumption_value"].sum() == pytest.approx(rs.totals["consumption_value"])


def test_share_sums_to_100(run):
    rs = run(measures=["consumption_value"], group_by=["payer_type"], show_share=True)
    assert rs.df["consumption_value__share"].sum() == pytest.approx(100, abs=0.01)


def test_top_n_is_ranked_and_limited(run):
    rs = run(measures=["consumption_value"], group_by=["doctor"], sort_by="consumption_value", limit=3)
    assert len(rs.df) == 3
    v = rs.df["consumption_value"].tolist()
    assert v == sorted(v, reverse=True)
    full = run(measures=["consumption_value"], group_by=["doctor"])
    assert v[0] == pytest.approx(full.df["consumption_value"].max())


# -- time -------------------------------------------------------------------------------------
def test_fiscal_year_boundaries(store, run):
    rs = run(time=TimeSpec(kind="fiscal_year", fiscal_year=2026))
    c = store.consumption
    want = c.loc[(c["Date"] >= "2025-04-01") & (c["Date"] <= "2026-03-31"), "Value"].sum()
    assert rs.totals["consumption_value"] == pytest.approx(want)


def test_fy_partly_outside_data_is_clipped_and_explained(run):
    rs = run(time=TimeSpec(kind="fiscal_year", fiscal_year=2025))
    assert any("data covers" in n for n in rs.notes)


def test_period_with_no_data_is_refused(cat, settings):
    with pytest.raises(PlanError):
        resolve_query(make_spec(time=TimeSpec(kind="fiscal_year", fiscal_year=2019)), cat, settings)


def test_relative_periods_anchor_on_asof_not_today(cat, settings):
    rq = resolve_query(make_spec(time=TimeSpec(kind="relative", unit="fiscal_year", count=1)), cat, settings)
    assert (rq.period.start.isoformat(), rq.period.end.isoformat()) == ("2025-04-01", "2026-03-31")
    rq = resolve_query(make_spec(time=TimeSpec(kind="trailing", unit="month", count=6)), cat, settings)
    assert (rq.period.start.isoformat(), rq.period.end.isoformat()) == ("2026-07-01", "2026-12-31")


def test_previous_period_is_like_for_like(cat, settings):
    rq = resolve_query(make_spec(time=TimeSpec(kind="relative", unit="fiscal_year", count=0)), cat, settings)
    prev = previous_period(rq.period)
    assert (prev.start.isoformat(), prev.end.isoformat()) == ("2025-04-01", "2025-12-31")   # same 9 months


def test_budget_widens_to_whole_months(cat, settings):
    rq = resolve_query(make_spec(measures=["budget_value"],
                                 time=TimeSpec(kind="between", start_date="2026-03-10", end_date="2026-03-20")),
                       cat, settings)
    assert rq.period.start.day == 1 and any("whole months" in n for n in rq.period.notes)


# -- entities and validation --------------------------------------------------------------------
def test_entity_matching(cat):
    info = cat.dim("department")
    assert match_value(info, "cardiology", 0.84)
    assert match_value(info, "Cardiolgy", 0.84)                     # typo
    assert match_value(info, "zzzz not a department", 0.84) is None


def test_unknown_entity_gives_suggestions(cat, settings):
    spec = make_spec(filters=[FilterSpec(dimension="department", op="in", values=["Podiatry Clinic"])])
    with pytest.raises(PlanError) as e:
        resolve_query(spec, cat, settings)
    assert e.value.suggestions


def test_dimension_not_on_table_is_refused(cat, settings):
    with pytest.raises(PlanError):
        resolve_query(make_spec(measures=["purchase_value"], group_by=["department"]), cat, settings)


def test_filter_matches_pandas(store, run):
    rs = run(filters=[FilterSpec(dimension="department", op="in", values=["Cardiology"])])
    c = store.consumption
    assert rs.totals["consumption_value"] == pytest.approx(c.loc[c["Dept_Name"] == "Cardiology", "Value"].sum())


def test_empty_result_is_explained(store, cat, run):
    """A real doctor on a single day on which they have no consumption rows."""
    c = store.consumption
    day = c["Date"].max()
    present = set(c.loc[c["Date"] == day, "Doctor"])
    doc = next(d for d in c["Doctor"].dropna().unique() if d not in present)
    iso = day.date().isoformat()
    rs = run(time=TimeSpec(kind="between", start_date=iso, end_date=iso),
             filters=[FilterSpec(dimension="doctor", op="in", values=[cat.dim("doctor").raw_to_label[doc]])])
    assert rs.empty and rs.empty_reason


def test_in_progress_period_is_labelled_to_date(cat, settings):
    rq = resolve_query(make_spec(time=TimeSpec(kind="relative", unit="fiscal_year", count=0)), cat, settings)
    assert "to date" in rq.period.label and rq.period.label.endswith("Dec 2026)")
    rq = resolve_query(make_spec(time=TimeSpec(kind="relative", unit="fiscal_year", count=1)), cat, settings)
    assert "to date" not in rq.period.label                      # a finished year is not "to date"
