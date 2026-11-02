"""
THE response envelope. Every dashboard endpoint returns this exact shape.

Why: KpiCard, DataTable and the chart wrappers are shared React components. If
each endpoint invents its own JSON, those components fork into five variants
and you lose the entire point of sharing them.
"""

from typing import Any, Literal

from pydantic import BaseModel


class Kpi(BaseModel):
    label: str
    value: float                     # raw number - frontend never parses strings
    display: str                     # "Rs 18.0 Cr" - pre-formatted for the card
    delta_pct: float | None = None   # vs prior period; None = no comparison
    tone: Literal["neutral", "positive", "risk"] = "neutral"
    # How this number is calculated, shown in small text under the card.
    # Any metric where we had to choose a definition carries one, so the
    # client can correct us in one sentence instead of quietly deciding the
    # dashboard is wrong.
    note: str | None = None


class ChartSeries(BaseModel):
    """One line/bar/slice group. data is a list of {x, y} style dicts."""
    name: str
    data: list[dict[str, Any]]



class Chart(BaseModel):
    id: str
    title: str
    type: Literal["line", "bar", "hbar", "stacked_bar", "donut", "area", "grouped_bar", "combo"]
    x_key: str
    series: list[ChartSeries]
    reference_line: float | None = None
    value_format: Literal["currency", "percent", "number"] = "currency"
    drilldown: dict[str, list[dict[str, Any]]] | None = None


class Table(BaseModel):
    columns: list[dict[str, str]]    # [{key, label, type}] - type drives formatting
    rows: list[dict[str, Any]]


class DashboardResponse(BaseModel):
    """The one shape all five endpoints return."""
    filters: dict[str, Any]
    kpis: list[Kpi]
    charts: list[Chart]
    table: Table
    insights: list[str]
    row_count: int                   # 0 => frontend shows the empty state


