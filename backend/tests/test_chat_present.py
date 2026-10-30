"""What the user sees: chart vs table choice, pivoted tables, stacked charts, and the facts behind the prose."""

import pytest

from app.chat.facts import build_facts
from app.chat.present import build_block
from app.chat.spec import TimeSpec


def test_table_is_collapsed_when_a_chart_shows_the_same_data(run, store):
    b = build_block(run(group_by=["department"]), store, "b1")
    assert b.charts and b.table and b.table_collapsed


def test_table_is_primary_when_no_chart_is_possible(run, store):
    b = build_block(run(group_by=["department"], chart="table_only"), store, "b1")
    assert not b.charts and b.table and not b.table_collapsed


def test_scalar_has_kpis_and_no_table(run, store):
    b = build_block(run(), store, "b1")
    assert b.kpis and b.table is None


def test_group_over_time_table_is_pivoted_with_a_total_column(run, store):
    rs = run(group_by=["department"], time_grain="month")
    b = build_block(rs, store, "b1")
    cols = [c["label"] for c in b.table.columns]
    assert cols[0] == "Period" and cols[-1] == "Total" and len(b.table.rows) == rs.df["_period"].nunique()
    row = b.table.rows[0]
    parts = sum(v for k, v in row.items() if k.startswith("g") and v is not None)
    assert row["_total"] == pytest.approx(parts, abs=0.05 * len(cols))
    # the pivoted figures are the engine's figures
    first = rs.df[rs.df["_period"] == row["_period"]]
    assert row["_total"] == pytest.approx(first["consumption_value"].sum(), abs=0.1 * len(cols))


def test_many_groups_over_time_become_a_stacked_chart_that_adds_up(run, store):
    rs = run(group_by=["department"], time_grain="month")
    b = build_block(rs, store, "b1")
    ch = b.charts[0]
    assert ch.type == "stacked_bar" and ch.series[-1].name == "All others"
    for i, p in enumerate(dict.fromkeys(rs.df["_period"])):
        stacked = sum(s.data[i]["value"] or 0 for s in ch.series)
        assert stacked == pytest.approx(rs.df.loc[rs.df["_period"] == p, "consumption_value"].sum())


def test_ratio_over_time_stays_a_line_chart(run, store):
    rs = run(measures=["formulary_compliance_pct"], group_by=["department"], time_grain="month")
    assert build_block(rs, store, "b1").charts[0].type == "line"


def test_over_time_facts_describe_the_combined_trend(run, store):
    rs = run(group_by=["department"], time_grain="month", time=TimeSpec(kind="relative", unit="fiscal_year", count=0))
    text = build_facts(rs, store).render_for_llm()
    assert "combined" in text and "Peak period" in text and "share of the window total" in text
