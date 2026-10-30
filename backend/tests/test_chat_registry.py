"""The registry, the plan schema and the generated prompt must agree with each other and with the data."""

from app.chat import prompts, semantic as sem
from app.chat.resolver import resolve_query
from app.chat.service import build_suggestions
from app.chat.spec import Plan


def test_registry_matches_live_data(cat):
    assert cat.problems == []


def test_every_measure_is_computable(run):
    """Each measure evaluates over the whole dataset without error."""
    for mid in sem.MEASURES:
        rs = run(measures=[mid])
        assert mid in rs.totals


def test_default_dimensions_are_valid(cat):
    for m in sem.MEASURES.values():
        tables = sem.measure_tables(m)
        for d in m.default_dims:
            assert d in sem.DIMENSIONS
            assert sem.dimension_supported_on(sem.DIMENSIONS[d], tables), (m.id, d)


def test_plan_schema_is_valid_for_structured_outputs():
    from openai.lib._pydantic import to_strict_json_schema
    schema = to_strict_json_schema(Plan)
    assert schema["type"] == "object"


def test_planner_prompt_mentions_every_id_and_the_asof_date(cat):
    text = prompts.planner_system_prompt()
    for mid in sem.MEASURES:
        assert mid in text
    for did in sem.DIMENSIONS:
        assert did in text
    assert cat.as_of.isoformat() in text


def test_prompt_examples_all_resolve(cat, settings):
    examples = prompts.build_examples(cat)
    assert len(examples) >= 6                       # none silently skipped
    for question, plan in examples:
        for spec in plan.queries:
            resolve_query(spec, cat, settings)


def test_suggestions_exist(cat):
    s = build_suggestions(cat)
    assert 4 <= len(s) <= 8 and len(set(s)) == len(s)


def test_measure_definitions_are_hashable():
    for m in sem.MEASURES.values():
        hash(m.expr)                       # the engine uses expressions as dict keys
