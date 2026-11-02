"""
The plan schema: the ONLY thing the planner LLM is allowed to produce.

Built from the semantic registry, so `measures` and `dimensions` are closed
enums - the model physically cannot name a metric or column that does not
exist. Free text is limited to filter VALUES (what the user typed), which the
resolver then maps onto real data values or rejects with suggestions.

NOTE: no `from __future__ import annotations` here - pydantic needs the real
Literal types at class-creation time.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model

from app.chat import semantic as sem

MeasureId = Literal[tuple(sem.MEASURES)]
DimensionId = Literal[tuple(sem.DIMENSIONS)]

TimeGrain = Literal["none", "month", "quarter", "fiscal_year", "year"]
ChartHint = Literal["auto", "line", "bar", "hbar", "stacked_bar", "donut",
                    "grouped_bar", "combo", "table_only"]
PeriodKind = Literal["all", "relative", "trailing", "fiscal_year", "calendar_year",
                     "month", "fiscal_quarter", "between"]
PeriodUnit = Literal["month", "quarter", "fiscal_year", "year"]


class TimeSpec(BaseModel):
    """
    The period, as symbols. The engine resolves it against the data's as-of
    date, so do NOT compute dates yourself.

    kind=all            whole dataset (use when the user gives no period)
    kind=relative       one whole period relative to now: unit + count
                        (count=0 this period, 1 previous, 2 the one before ...)
    kind=trailing       the last `count` periods up to now, e.g. last 6 months
    kind=fiscal_year    fiscal_year=2026 means FY2026
    kind=calendar_year  calendar_year=2026
    kind=month          calendar_year + month (1-12)
    kind=fiscal_quarter fiscal_year + quarter (1-4)
    kind=between        start_date / end_date as YYYY-MM-DD
    """
    kind: PeriodKind
    unit: Optional[PeriodUnit] = Field(None, description="For relative/trailing.")
    count: Optional[int] = Field(None, description="Periods back (relative) or how many (trailing).")
    fiscal_year: Optional[int] = None
    calendar_year: Optional[int] = None
    month: Optional[int] = None
    quarter: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class FilterSpec(BaseModel):
    dimension: DimensionId
    op: Literal["in", "not_in"]
    values: list[str] = Field(description="Values exactly as the user said them; they are matched to real data values afterwards.")


class QuerySpec(BaseModel):
    title: str = Field(description="Short chart/table title, 3-8 words.")
    measures: list[MeasureId] = Field(description="1-4 measures to compute.")
    group_by: list[DimensionId] = Field(description="0-2 dimensions to break the measures down by.")
    time_grain: TimeGrain = Field(description="'none' for a single figure/breakdown; month/quarter/fiscal_year/year for a trend over time.")
    time: TimeSpec
    filters: list[FilterSpec]
    sort_by: Optional[MeasureId] = Field(None, description="Measure to rank groups by (defaults to the first measure).")
    sort_desc: bool = True
    limit: Optional[int] = Field(None, description="Top-N groups, e.g. 'top 5 doctors'. Null for all.")
    show_share: bool = Field(False, description="Add each group's % of the total (only for additive measures).")
    compare_previous: bool = Field(False, description="Compare with the equally long preceding period.")
    chart: ChartHint = "auto"


class Plan(BaseModel):
    """
    action=query         answer with 1-3 queries.
    action=clarify       the question is genuinely ambiguous: put ONE short question in `message`.
    action=out_of_scope  this dataset cannot answer it: say why in `message`.
    action=chat          greeting / what can you do: reply in `message`.
    """
    action: Literal["query", "clarify", "out_of_scope", "chat"]
    message: Optional[str] = None
    queries: list[QuerySpec]


def parse_query_spec(data: dict) -> Optional[QuerySpec]:
    """Tolerant parse used for conversation history echoed back by the client."""
    try:
        return QuerySpec.model_validate(data)
    except Exception:
        return None
