"""End to end through the real HTTP endpoint with a scripted model (no network)."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.chat.router as chat_router
from app.chat.llm import LLMError
from app.chat.narrative import Narration
from app.chat.service import ChatService
from app.chat.spec import FilterSpec, Plan, TimeSpec
from app.main import app
from conftest import FakeLLM, make_spec

client = TestClient(app)


def _plan(*specs, action="query", message=None):
    return Plan(action=action, message=message, queries=list(specs))


def _narr(text="Done.", follow=("Show it monthly",)):
    return Narration(headline=text, insights=[], recommendations=[], follow_ups=list(follow))


def _post(monkeypatch, settings, llm, question="q", history=None):
    svc = ChatService(settings, llm)
    monkeypatch.setattr(chat_router, "get_service", lambda: svc)
    r = client.post("/api/chat", json={"question": question, "history": history or []})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events, cur = [], None
    for line in r.text.splitlines():
        if line.startswith("event: "):
            cur = line[7:]
        elif line.startswith("data: "):
            events.append((cur, json.loads(line[6:])))
    return events


def _names(events):
    return [n for n, _ in events]


def test_full_answer_streams_results_then_narrative(monkeypatch, settings_with_key):
    plan = _plan(make_spec(title="Consumption by department", group_by=["department"]))
    # placeholder f1 is always the first fact registered
    llm = FakeLLM([plan], [_narr("Total is {f1}.")])
    ev = _post(monkeypatch, settings_with_key, llm, "consumption by department")
    names = _names(ev)
    assert names[-1] == "done" and "result" in names and names.index("result") < names.index("narrative")
    block = next(d for n, d in ev if n == "result")["block"]
    assert block["table"]["rows"] and block["charts"] and block["scope"]
    narr = next(d for n, d in ev if n == "narrative")
    assert "{f" not in narr["headline"] and narr["source"] == "llm"


def test_scalar_gets_kpis(monkeypatch, settings_with_key):
    llm = FakeLLM([_plan(make_spec(measures=["formulary_compliance_pct"]))], [_narr("Compliance is {f1}.")])
    block = next(d for n, d in _post(monkeypatch, settings_with_key, llm) if n == "result")["block"]
    assert block["kpis"] and block["kpis"][0]["display"].endswith("%")


def test_clarify_and_out_of_scope_skip_the_engine(monkeypatch, settings_with_key):
    for action in ("clarify", "out_of_scope", "chat"):
        llm = FakeLLM([_plan(action=action, message="Hello there")])
        ev = _post(monkeypatch, settings_with_key, llm)
        assert ("message", {"kind": action, "text": "Hello there"}) in ev
        assert "result" not in _names(ev) and llm.narrate_calls == []


def test_unknown_entity_answers_with_suggestions_without_a_repair_call(monkeypatch, settings_with_key):
    spec = make_spec(filters=[FilterSpec(dimension="department", op="in", values=["Podiatry Clinic"])])
    llm = FakeLLM([_plan(spec)])
    ev = _post(monkeypatch, settings_with_key, llm)
    msg = next(d for n, d in ev if n == "message")
    assert msg["kind"] == "not_found" and "Podiatry" in msg["text"] and len(llm.plan_calls) == 1


def test_invalid_plan_is_repaired_once(monkeypatch, settings_with_key):
    bad = _plan(make_spec(measures=["purchase_value"], group_by=["department"]))     # purchases have no department
    good = _plan(make_spec(measures=["purchase_value"], group_by=["vendor"]))
    llm = FakeLLM([bad, good], [_narr("Purchases are {f1}.")])
    ev = _post(monkeypatch, settings_with_key, llm)
    assert "result" in _names(ev) and len(llm.plan_calls) == 2
    assert "rejected" in llm.plan_calls[1][1][-1]["content"]


def test_fallback_model_is_used_when_primary_unavailable(monkeypatch, settings_with_key):
    s = replace(settings_with_key, planner_model="primary-x", planner_fallback_model="fallback-y")
    llm = FakeLLM([LLMError("model_unavailable", "nope"), _plan(make_spec())], [_narr("Total {f1}.")])
    ev = _post(monkeypatch, s, llm)
    assert "result" in _names(ev) and [m for m, _ in llm.plan_calls] == ["primary-x", "fallback-y"]


def test_unrecoverable_plan_returns_a_polite_message(monkeypatch, settings_with_key):
    bad = _plan(make_spec(measures=["purchase_value"], group_by=["department"]))
    llm = FakeLLM([bad] * 6)
    ev = _post(monkeypatch, settings_with_key, llm)
    assert next(d for n, d in ev if n == "message")["kind"] == "failed"


def test_model_down_gives_error_event_not_a_crash(monkeypatch, settings_with_key):
    ev = _post(monkeypatch, settings_with_key, FakeLLM([LLMError("rate_limit", "x")]))
    assert next(d for n, d in ev if n == "error")["kind"] == "rate_limit"


def test_narrator_down_still_returns_correct_answer(monkeypatch, settings_with_key):
    llm = FakeLLM([_plan(make_spec(group_by=["department"]))], [LLMError("timeout", "x")])
    ev = _post(monkeypatch, settings_with_key, llm)
    narr = next(d for n, d in ev if n == "narrative")
    assert narr["source"] == "fallback" and narr["headline"]


def test_missing_key_is_reported(monkeypatch, settings_with_key):
    ev = _post(monkeypatch, replace(settings_with_key, api_key=""), FakeLLM())
    assert next(d for n, d in ev if n == "error")["kind"] == "not_configured"


def test_input_validation(monkeypatch, settings_with_key):
    assert next(d for n, d in _post(monkeypatch, settings_with_key, FakeLLM(), "   ") if n == "error")["kind"] == "empty"
    long_q = "x" * (settings_with_key.max_question_chars + 1)
    assert next(d for n, d in _post(monkeypatch, settings_with_key, FakeLLM(), long_q) if n == "error")["kind"] == "too_long"


def test_history_reaches_the_planner(monkeypatch, settings_with_key):
    first = make_spec(title="Consumption by dept", group_by=["department"]).model_dump(mode="json")
    llm = FakeLLM([_plan(make_spec())], [_narr("x {f1}")])
    _post(monkeypatch, settings_with_key, llm, "and for Goa?",
          history=[{"question": "consumption by department", "specs": [first, {"junk": 1}], "answer": "ok"}])
    prompt = llm.plan_calls[0][1][0]["content"]
    assert "consumption by department" in prompt and '"group_by":["department"]' in prompt and "junk" not in prompt


def test_repeat_question_hits_the_cache_and_skips_the_model(monkeypatch, settings_with_key):
    svc = ChatService(settings_with_key, FakeLLM([_plan(make_spec())], [_narr("Total {f1}.")]))
    monkeypatch.setattr(chat_router, "get_service", lambda: svc)
    for _ in range(2):
        r = client.post("/api/chat", json={"question": "total consumption", "history": []})
        assert "event: narrative" in r.text
    assert len(svc.llm.plan_calls) == 1 and len(svc.llm.narrate_calls) == 1


def test_too_many_queries_are_capped_with_a_note(monkeypatch, settings_with_key):
    specs = [make_spec(title=f"q{i}", group_by=[d]) for i, d in enumerate(["department", "payer_type", "patient_type", "unit"])]
    llm = FakeLLM([_plan(*specs)], [_narr("x {f1}")])
    ev = _post(monkeypatch, settings_with_key, llm)
    results = [d["block"] for n, d in ev if n == "result"]
    assert len(results) == settings_with_key.max_queries_per_plan
    assert any("showing the first" in n for n in results[0]["notes"])


def test_suggestions_and_health_endpoints():
    s = client.get("/api/chat/suggestions").json()["suggestions"]
    assert len(s) >= 4
    h = client.get("/api/chat/health").json()
    assert h["registry_problems"] == [] and "models" in h


def test_rate_limiter():
    from app.chat.util import RateLimiter
    rl = RateLimiter(2)
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a") and rl.allow("b")


def test_existing_dashboard_endpoints_still_work():
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/consumption").status_code == 200


def test_missing_sdk_gives_actionable_error(monkeypatch):
    """If `openai` is not installed the user sees how to fix it, not a generic 'internal' error."""
    import builtins
    import pytest
    from app.chat.llm import LLM, LLMError, USER_MESSAGES
    from app.chat.settings import get_settings

    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "openai":
            raise ModuleNotFoundError("No module named 'openai'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    llm = LLM(get_settings())
    with pytest.raises(LLMError) as ei:
        llm._get_client.__func__  # noqa: B018  (sanity: method exists)
        import asyncio
        asyncio.run(llm._parse(model="m", system="s", messages=[], schema=object, effort="",
                               max_tokens=1, cache_key="k", tag="t"))
    assert ei.value.kind == "not_installed"
    assert "requirements.txt" in USER_MESSAGES["not_installed"]
