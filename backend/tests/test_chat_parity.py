"""
The chat engine must report the SAME figures as the dashboards for the same
scope. Each case calls a real dashboard endpoint and the chat engine with
equivalent filters and compares every shared KPI.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.chat.spec import FilterSpec, TimeSpec

client = TestClient(app)

# dashboard endpoint -> {KPI label: chat measure id}
PARITY = {
    "consumption": {"Total Consumption Value": "consumption_value", "Total Qty Consumed": "consumption_qty",
                    "IP Share": "ip_share_pct", "Budget": "budget_value",
                    "Budget Utilisation": "budget_utilisation_pct"},
    "formulary-compliance": {"Formulary Compliance": "formulary_compliance_pct",
                             "On-Formulary Value": "on_formulary_value",
                             "Off-Formulary Value": "off_formulary_value",
                             "Off-Formulary Items": "off_formulary_item_count"},
    "inventory-analysis": {"Inventory Days": "inventory_days", "Inventory Value": "stock_value",
                           "HIS Consumption": "consumption_value", "HIS Non-Implant Cons": "non_implant_value"},
    "sob-compliance": {"SOB Compliance": "sob_compliance_pct", "Preferred Brand Value": "preferred_brand_value",
                       "Non-Preferred Value": "non_preferred_value",
                       "Switchable Opportunity": "switchable_opportunity_value"},
    "sob-opportunities": {"Total Opportunity": "switchable_opportunity_value",
                          "% of Consumption": "switchable_opportunity_pct"},
}

RANGES = [("2025-01-01", "2026-12-31"), ("2025-04-01", "2026-03-31"),
          ("2026-04-01", "2026-12-31"), ("2025-10-01", "2025-12-31"), ("2026-03-01", "2026-03-31")]


def _scopes(store):
    """Filter combinations built from the data itself: (dashboard params, chat filters)."""
    units = sorted(store.consumption["Unit_ID"].unique())
    depts = sorted(store.consumption["Dept_Name"].dropna().unique())
    groups = sorted(store.consumption["Stock Take Group"].dropna().unique())
    yield {}, []
    yield {"unit": units[0]}, [("unit", units[0])]
    yield {"department": depts[0]}, [("department", depts[0])]
    yield {"stock_take_group": groups[0]}, [("stock_take_group", groups[0])]
    yield {"unit": units[-1], "department": depts[1]}, [("unit", units[-1]), ("department", depts[1])]


def _cases(store):
    for dash, chat_filters in _scopes(store):
        for rng in RANGES:
            yield dash, chat_filters, rng


@pytest.fixture(scope="module")
def cases(store):
    return list(_cases(store))


def _tolerance(unit):
    return {"percent": 0.011, "days": 0.06}.get(unit, 0.51)


def test_chat_engine_equals_dashboards(store, cat, run, cases):
    import app.chat.semantic as sem
    checked = 0
    for dash, chat_filters, (lo, hi) in cases:
        filters = []
        for dim, raw in chat_filters:
            label = cat.dim(dim).raw_to_label[raw]
            filters.append(FilterSpec(dimension=dim, op="in", values=[label]))
        for endpoint, kmap in PARITY.items():
            resp = client.get(f"/api/{endpoint}", params={**dash, "date_from": lo, "date_to": hi})
            assert resp.status_code == 200
            kpis = {k["label"]: k["value"] for k in resp.json()["kpis"]}
            for label, mid in kmap.items():
                if label not in kpis or kpis[label] is None:
                    continue
                if mid == "stock_value" and "stock_take_group" in dash:
                    pass
                rs = run(measures=[mid], time=TimeSpec(kind="between", start_date=lo, end_date=hi),
                         filters=filters)
                got = rs.totals.get(mid)
                unit = sem.MEASURES[mid].unit
                assert got is not None, (endpoint, label, dash, lo, hi)
                assert abs(got - kpis[label]) <= _tolerance(unit), \
                    f"{endpoint}/{label} dash={kpis[label]} chat={got} scope={dash} {lo}..{hi}"
                checked += 1
    assert checked > 300
