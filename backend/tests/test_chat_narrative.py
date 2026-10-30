"""The narration guarantee: no figure reaches the user unless WE computed it."""

import asyncio

from app.chat.facts import build_facts
from app.chat.llm import LLMError
from app.chat.narrative import (CombinedFacts, Narration, build_narrative, fallback_narrative,
                                render, verify)
from conftest import FakeLLM


def _combined(run, store, **kw):
    rs = run(**kw)
    return rs, CombinedFacts([(rs.query.title, build_facts(rs, store))])


def _ids(c, label_part):
    return [f.id for f in c.facts.values() if label_part.lower() in f.label.lower()]


def test_placeholders_are_replaced_with_exact_figures(run, store):
    rs, c = _combined(run, store, group_by=["department"])
    fid = _ids(c, "Highest department")[0]
    n = Narration(headline=f"Top spend is {{{fid}}}.", insights=[], recommendations=[], follow_ups=[])
    assert verify(n, c, c.allowed_digit_runs()) == []
    out = render(n, c)
    assert c.facts[fid].display in out.headline and "{" not in out.headline


def test_typed_numbers_are_rejected(run, store):
    _, c = _combined(run, store, group_by=["department"])
    bad = Narration(headline="Spend was 12.5 Cr.", insights=[], recommendations=[], follow_ups=[])
    assert verify(bad, c, c.allowed_digit_runs())


def test_numbers_from_question_and_scope_are_allowed(run, store):
    _, c = _combined(run, store, group_by=["department"])
    n = Narration(headline="Top 5 departments shown.", insights=[], recommendations=[], follow_ups=[])
    assert verify(n, c, c.allowed_digit_runs("show top 5 departments")) == []
    assert verify(n, c, c.allowed_digit_runs())            # "5" not in question or scope -> rejected


def test_unknown_placeholder_is_rejected(run, store):
    _, c = _combined(run, store)
    n = Narration(headline="It is {f999}.", insights=[], recommendations=[], follow_ups=[])
    assert verify(n, c, c.allowed_digit_runs())


def test_multi_block_ids_do_not_collide(run, store):
    rs1, rs2 = run(group_by=["department"]), run(group_by=["payer_type"])
    c = CombinedFacts([("a", build_facts(rs1, store)), ("b", build_facts(rs2, store))])
    ids = [f.id for f in c.facts.values()]
    assert len(ids) == len(set(ids))
    # every placeholder used in the fallback text resolves to a real value
    head, rest = c.fallback_sentences()
    assert "{f" not in head and all("{f" not in r for r in rest)


def _good(c):
    fid = _ids(c, "overall")[0]
    return Narration(headline=f"Overall is {{{fid}}}.", insights=[], recommendations=[], follow_ups=["Break it down by payer type"])


def test_build_narrative_happy_path(run, store, settings):
    rs, c = _combined(run, store, group_by=["department"])
    llm = FakeLLM(narrations=[_good(c)])
    out = asyncio.run(build_narrative(llm, settings, "q", c, [rs.query]))
    assert out.source == "llm" and len(llm.narrate_calls) == 1


def test_build_narrative_retries_once_then_succeeds(run, store, settings):
    rs, c = _combined(run, store, group_by=["department"])
    bad = Narration(headline="Spend was 99 Cr.", insights=[], recommendations=[], follow_ups=[])
    llm = FakeLLM(narrations=[bad, _good(c)])
    out = asyncio.run(build_narrative(llm, settings, "q", c, [rs.query]))
    assert out.source == "llm" and len(llm.narrate_calls) == 2
    assert "Rejected" in llm.narrate_calls[1][-1]["content"]


def test_build_narrative_falls_back_after_two_bad_answers(run, store, settings):
    rs, c = _combined(run, store, group_by=["department"])
    bad = Narration(headline="Spend was 99 Cr.", insights=[], recommendations=[], follow_ups=[])
    out = asyncio.run(build_narrative(FakeLLM(narrations=[bad, bad]), settings, "q", c, [rs.query]))
    assert out.source == "fallback" and "99" not in out.headline and out.headline


def test_build_narrative_falls_back_when_model_is_down(run, store, settings):
    rs, c = _combined(run, store, group_by=["department"])
    out = asyncio.run(build_narrative(FakeLLM(narrations=[LLMError("timeout", "slow")]), settings, "q", c, [rs.query]))
    assert out.source == "fallback" and out.headline


def test_fallback_has_no_raw_placeholders(run, store):
    for kw in [dict(), dict(group_by=["department"]), dict(time_grain="month"),
               dict(group_by=["payer_type"], time_grain="quarter"),
               dict(measures=["formulary_compliance_pct"], group_by=["department"], compare_previous=True)]:
        rs, c = _combined(run, store, **kw)
        n = fallback_narrative(c, [rs.query])
        assert "{f" not in n.headline and all("{f" not in i for i in n.insights)


def test_units_next_to_placeholders_are_rejected(run, store):
    _, c = _combined(run, store, group_by=["department"])
    fid = _ids(c, "overall")[0]
    for text in (f"Total is {{{fid}}} Cr.", f"Total is ₹{{{fid}}}.", f"Up {{{fid}}}%."):
        n = Narration(headline=text, insights=[], recommendations=[], follow_ups=[])
        assert verify(n, c, c.allowed_digit_runs()), text
