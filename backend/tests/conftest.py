"""
Shared fixtures. No test here calls OpenAI: the model is replaced by FakeLLM,
so the suite is fast, free and deterministic. The real model is exercised by
tests/live_smoke.py (run once by hand when the API key is in place).
"""

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must be set before app.chat.settings is first imported.
os.environ["CHAT_RATE_LIMIT_PER_MIN"] = "0"
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")

from app.chat.catalog import get_catalog                      # noqa: E402
from app.chat.engine import execute                           # noqa: E402
from app.chat.resolver import resolve_query                   # noqa: E402
from app.chat.settings import get_settings                    # noqa: E402
from app.chat.spec import QuerySpec, TimeSpec                 # noqa: E402
from app.data_loader import get_store                         # noqa: E402


@pytest.fixture(scope="session")
def store():
    return get_store()


@pytest.fixture(scope="session")
def cat(store):
    return get_catalog()


@pytest.fixture(scope="session")
def settings():
    return get_settings()


def make_spec(**kw) -> QuerySpec:
    base = dict(title="t", measures=["consumption_value"], group_by=[], time_grain="none",
                time=TimeSpec(kind="all"), filters=[], sort_by=None, sort_desc=True, limit=None,
                show_share=False, compare_previous=False, chart="auto")
    base.update(kw)
    return QuerySpec(**base)


@pytest.fixture(scope="session")
def run(store, cat, settings):
    """run(**spec fields) -> ResultSet, via the same resolve+execute path the chat uses."""
    def _run(**kw):
        return execute(store, cat, resolve_query(make_spec(**kw), cat, settings), 200)
    return _run


class FakeLLM:
    """Stands in for app.chat.llm.LLM. `plans` / `narrations` are consumed in order;
    a callable is invoked with (system, messages) so a test can inspect the prompt."""

    def __init__(self, plans=(), narrations=()):
        self.plans, self.narrations = list(plans), list(narrations)
        self.plan_calls, self.narrate_calls = [], []

    async def plan(self, system, messages, model=None):
        self.plan_calls.append((model, messages))
        item = self.plans.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def narrate(self, system, messages):
        self.narrate_calls.append(messages)
        item = self.narrations.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def ping(self, model):
        return None


@pytest.fixture
def settings_with_key(settings):
    return replace(settings, api_key="test-key-not-real", enabled=True)
