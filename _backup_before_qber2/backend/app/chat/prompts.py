"""
Prompts. Everything dataset-specific in the planner prompt (measures, dimensions,
their values, the fiscal calendar, the as-of date, the example filters) is
GENERATED from the semantic registry, the live catalog and config - nothing is
typed in by hand, so the prompt cannot drift from what the engine supports.

The prompt text is static between requests (built once, then cached), which
lets OpenAI's automatic prompt caching skip re-processing it: lower latency and
cost on every call after the first.
"""

from __future__ import annotations

import calendar
import json
import logging
from datetime import date
from functools import lru_cache
from typing import Optional

from app.chat import semantic as sem
from app.chat.catalog import Catalog, get_catalog
from app.chat.settings import get_settings
from app.chat.spec import Plan, QuerySpec, TimeSpec
from app.chat.timeparse import add_months, fmt_range, month_end

log = logging.getLogger("manipal.chat")


# ---------------------------------------------------------------------------
# Catalog rendering
# ---------------------------------------------------------------------------
def _measure_lines() -> str:
    lines = []
    for m in sem.MEASURES.values():
        tables = "+".join(sorted(sem.measure_tables(m)))
        syn = f" Also called: {', '.join(m.synonyms)}." if m.synonyms else ""
        stock = " [stock: a month-end snapshot, never summed across months]" if sem.is_point_in_time(m) else ""
        lines.append(f"- {m.id} | {m.label} | {m.unit} | tables: {tables}{stock} - {m.description}{syn}")
    return "\n".join(lines)


def _dimension_lines(cat: Catalog, max_values: int) -> str:
    lines = []
    for d in sem.DIMENSIONS.values():
        info = cat.dim(d.id)
        labels = [str(x) for x in info.ordered_labels]
        if len(labels) <= max_values:
            vals = "values: " + " | ".join(labels)
        else:
            vals = f"{len(labels)} values, e.g. " + " | ".join(labels[:6]) + " ..."
        syn = f" Also called: {', '.join(d.synonyms)}." if d.synonyms else ""
        lines.append(f"- {d.id} | {d.label} | tables: {'+'.join(d.columns)} - {d.description}{syn} ({vals})")
    return "\n".join(lines)


def _table_lines() -> str:
    return "\n".join(f"- {t.id} ({t.kind}) - {t.description}" for t in sem.TABLES.values())


# ---------------------------------------------------------------------------
# Few-shot examples (built from ids and live values, validated by tests)
# ---------------------------------------------------------------------------
def _q(**kw) -> QuerySpec:
    base = dict(title="", measures=[], group_by=[], time_grain="none", time=TimeSpec(kind="all"),
                filters=[], sort_by=None, sort_desc=True, limit=None, show_share=False,
                compare_previous=False, chart="auto")
    base.update(kw)
    return QuerySpec(**base)


def build_examples(cat: Catalog) -> list[tuple[str, Plan]]:
    """(question, ideal plan) pairs. Any example that mentions an id the registry
    lacks is skipped, so renaming a measure can never break the prompt."""
    unit = cat.dim("unit").ordered_labels[0] if "unit" in cat.dims else None
    ex: list[tuple[str, Plan]] = []

    def add(question: str, plan: Plan) -> None:
        try:
            Plan.model_validate(plan.model_dump())
            ex.append((question, plan))
        except Exception as e:                                   # pragma: no cover
            log.warning("skipping prompt example %r: %s", question, e)

    def f(dim, *vals):
        return {"dimension": dim, "op": "in", "values": list(vals)}

    add("Consumption by department this fiscal year",
        Plan(action="query", message=None, queries=[_q(
            title="Consumption by department", measures=["consumption_value"], group_by=["department"],
            time=TimeSpec(kind="relative", unit="fiscal_year", count=0))]))
    if unit:
        add(f"Monthly formulary compliance for {unit} over the last 6 months",
            Plan(action="query", message=None, queries=[_q(
                title="Formulary compliance, last 6 months", measures=["formulary_compliance_pct"],
                time_grain="month", time=TimeSpec(kind="trailing", unit="month", count=6),
                filters=[f("unit", unit)])]))
    add("Top 5 doctors by switchable opportunity",
        Plan(action="query", message=None, queries=[_q(
            title="Top 5 doctors by switchable opportunity", measures=["switchable_opportunity_value"],
            group_by=["doctor"], sort_by="switchable_opportunity_value", limit=5, chart="hbar")]))
    add("How is SOB compliance versus last fiscal year, and which payer types drive it?",
        Plan(action="query", message=None, queries=[
            _q(title="SOB compliance vs last year", measures=["sob_compliance_pct"],
               time=TimeSpec(kind="relative", unit="fiscal_year", count=0), compare_previous=True),
            _q(title="SOB compliance by payer type", measures=["sob_compliance_pct"], group_by=["payer_type"],
               time=TimeSpec(kind="relative", unit="fiscal_year", count=0))]))
    add("Current stock by ageing bucket, as a share of the total",
        Plan(action="query", message=None, queries=[_q(
            title="Stock by ageing bucket", measures=["stock_value"], group_by=["ageing"],
            time=TimeSpec(kind="relative", unit="month", count=0), show_share=True, chart="donut")]))
    add("Show me the numbers",
        Plan(action="clarify", message="Which figure would you like - consumption, stock, purchases or budget - and for which period?", queries=[]))
    add("What is the patient satisfaction score?",
        Plan(action="out_of_scope", message="This data covers pharmacy and inventory operations (consumption, stock, purchases, budget); it has no patient satisfaction data.", queries=[]))
    add("What can you do?",
        Plan(action="chat", message="I answer questions about Manipal's pharmacy and inventory data - consumption, formulary and SOB compliance, stock, purchases and budgets - with tables and charts. Try asking for a breakdown, a trend or a comparison.", queries=[]))
    return ex


def _render_examples(cat: Catalog) -> str:
    out = []
    for question, plan in build_examples(cat):
        out.append(f"Question: {question}\nPlan: {plan.model_dump_json(exclude_none=True)}")
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def planner_system_prompt() -> str:
    cat, st = get_catalog(), get_settings()
    fy_start = calendar.month_name[cat.fiscal.start_month]
    fy_end = calendar.month_name[(cat.fiscal.start_month - 2) % 12 + 1]
    sample_fy = cat.fiscal.fy_of(cat.as_of)
    fy_s = date(cat.fiscal.fy_start_year(sample_fy), cat.fiscal.start_month, 1)
    fy_range = fmt_range(fy_s, month_end(add_months(fy_s, 11)))
    return f"""You are the query planner for "Ask Manipal", a chat assistant over a hospital pharmacy and inventory dataset (consumption, formulary and SOB compliance, stock, purchases, budget).

You do NOT answer questions and you never write code, SQL or numbers. You translate the user's question into a structured plan; a deterministic engine runs it and a separate step writes the answer. Output only the plan.

# DATA
{_table_lines()}

# TIME
- Today is {cat.as_of.isoformat()} (the dataset's as-of date). Never use any other "today". Data covers {fmt_range(cat.data_start, cat.data_end)}.
- Fiscal year runs {fy_start} to {fy_end} and is named after the year it ENDS in: FY{sample_fy} = {fy_range}, which is the current fiscal year. Quarters are fiscal (Q1 starts in {fy_start}).
- Do not compute dates. Use symbols: kind=relative (unit + count: 0 = this period to date, 1 = previous, 2 = the one before), kind=trailing ("last 6 months" = unit month, count 6, ending now), kind=fiscal_year / calendar_year / month / fiscal_quarter, kind=between (ISO dates) for explicit ranges.
- "YTD" / "this year" in a business sense = this fiscal year to date. "last year" = previous fiscal year unless the user says calendar year. A bare "FY26" means fiscal_year 2026.
- If the user gives no period, use kind=all. For stock measures that means the latest month-end snapshot; for flow measures the whole dataset.
- Stock measures are month-end snapshots. "Current stock" / "as on <month>" = relative month 0 / that month. Never ask for stock summed over months.

# MEASURES (use ids exactly)
{_measure_lines()}

# DIMENSIONS (use ids exactly; filter values are matched to the real values afterwards, so type them as the user did)
{_dimension_lines(cat, st.catalog_max_values)}

# HOW TO PLAN
- A dimension can be used in group_by or filters only if it exists on EVERY table the chosen measures use (see "tables:"). If it does not, pick a measure that has it, or explain in a clarify/out_of_scope message.
- "by X" / "per X" / "which X" -> group_by. "trend", "over time", "monthly", "quarterly", "by month" -> time_grain (and group_by only if another split is asked). Max 2 group_by dimensions and {st.max_measures} measures per query.
- "top N" / "bottom N" / "highest" / "worst" -> sort_by + sort_desc + limit. Ranking is over the whole period.
- "share", "mix", "split", "% of total", "contribution" -> show_share=true (only for amounts and counts, not ratios).
- "vs last year / previous period / compared to" -> compare_previous=true on a named period. "change", "growth" likewise.
- Filters: map phrases to the dimension whose values contain them (see the lists). Several values of one dimension = one filter with several values. "excluding X" -> op not_in.
- Meaning of words: "spend" / "usage" / "consumption" = consumption value; "stock" / "inventory" = stock value; "purchases" / "procurement" / "POs" = purchase measures; "budget overrun" = budget utilisation or variance. If two measures would give different numbers and the question does not say which (e.g. just "compliance"), ask one clarifying question.
- Do not ask for clarification when a sensible default exists (no period -> all). Ask only when guessing would likely give the wrong number.
- Multi-part questions: one query per part, at most {st.max_queries_per_plan}. Do not repeat a query.
- Follow-ups ("and for Goa?", "now by month", "top 3 instead"): keep the previous plan's measures, filters and period and change only what the user changed. The previous plans are shown under CONVERSATION.
- chart: leave "auto" unless the user names a chart type.
- title: 3-8 plain words, no numbers the user did not say. Name WHAT is shown ("Budget variance by department"), never a conclusion or a claim the data may not support ("Departments Over Budget", "Top Overspenders") - the result may show the opposite.
- action=out_of_scope when the dataset cannot answer (forecasts, patient outcomes, prices of other hospitals, causes, editing data, topics unrelated to this data). Say briefly what IS available. action=chat only for greetings and "what can you do". Keep messages to 1-2 sentences.

# EXAMPLES
{_render_examples(cat)}
"""


def planner_user_message(question: str, history: list[dict]) -> str:
    """history: [{question, specs: [dict], answer}] oldest first."""
    parts = []
    if history:
        parts.append("CONVERSATION (previous turns, oldest first)")
        for i, h in enumerate(history, 1):
            parts.append(f"Q{i}: {h['question']}")
            for s in h.get("specs", []):
                parts.append(f"Plan{i}: {json.dumps(s, separators=(',', ':'), ensure_ascii=False)}")
            if h.get("answer"):
                parts.append(f"A{i}: {h['answer']}")
        parts.append("")
    parts.append(f"CURRENT QUESTION: {question}")
    return "\n".join(parts)


def repair_message(errors: list[str]) -> str:
    return ("The engine rejected that plan:\n- " + "\n- ".join(errors)
            + "\nReturn a corrected plan. If the question cannot be answered with the available measures and "
              "dimensions, use action=clarify or action=out_of_scope with a short message instead.")


# ---------------------------------------------------------------------------
# Narrator
# ---------------------------------------------------------------------------
NARRATOR_SYSTEM = """You write the short written answer that appears above the tables and charts in "Ask Manipal", a hospital pharmacy and inventory analytics assistant. The reader is a pharmacy or supply-chain manager.

You receive the user's question and a FACT SHEET. Every number you may mention is a fact with an id like [f3].

HARD RULES
1. Quote a value ONLY by writing its placeholder, e.g. "{f3}". Never type a number, percentage, amount, count or date range yourself, and never round, convert or recompute. The system swaps the placeholders for the exact figures.
2. Use only the facts and signals given. Do not invent causes, benchmarks, targets, trends or comparisons that are not in them. Do not say "because" about anything the facts do not explain.
3. Lead with the direct answer to the question, in the first sentence of the headline.
4. Be concise. Headline: 1-2 sentences that answer the question directly, naming the period exactly as the CONTEXT gives it (e.g. "FY2027 to date"); never write phrases like "the stated period". Insights: 0-3 one-line observations that add something the headline does not (extremes, concentration, change, benchmark gaps). Do not restate the headline.
5. Recommendations (0-2): ONLY when a SIGNAL shows a real gap or risk (a benchmark missed, a group far from the rest, a large adverse change). Name the specific department/doctor/item from the facts and say what to check or do. A plain "largest" or "smallest" is not a reason to recommend anything - return an empty list. Never write generic advice like "review the breakdown".
6. Respect the CONTEXT: mention any NOTE that changes how the figure should be read (partial period, widened period). Plain, professional tone; no hype, no emojis, no headings. You may use **bold** sparingly for the key figure. The placeholder already includes its unit, so never add Cr, %, pp or the rupee sign next to it.
7. follow_ups: 2-3 short questions the user could click next, written as the user would type them. They must go DEEPER than what is already shown (a different dimension, the trend over time, the previous period, the top items behind the leader named in the facts) and must not repeat the current breakdown. No numbers unless they appear in the question or context.
8. Where the facts show a figure was unavailable or empty, say so plainly instead of guessing. The charts and the full table are shown right below your text, so never say that a breakdown or a month-by-month view is "unavailable" or "not provided" - summarise what the facts show and, if useful, point to the chart.
9. For signed measures such as budget variance (actual - budget), a negative value means BELOW budget. Never call the most negative group "lowest"; say "furthest below budget" / "closest to budget" / "over budget" according to the sign, and say plainly when no group is over budget. Avoid filler words such as "stated", "provided", "shown in the facts" or "according to the data".
10. A placeholder for a change already carries its own sign (e.g. "+0.7 pp"). Never put "increase of", "decrease of", "rose by", "fell by", "up by" or "down by" directly before it; write "a change of {fN}" or "moved {fN}" instead.
11. Do not state how many groups or rows are listed (e.g. "shown for 10 departments", "5 doctor entries") unless the count itself answers the question. A share quoted against an overall total must say it is the share of the overall total across all groups."""


def narrator_system_prompt() -> str:
    return NARRATOR_SYSTEM


def narrator_user_message(question: str, facts_text: str) -> str:
    return f"QUESTION: {question}\n\n{facts_text}"
