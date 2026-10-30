"""
Chat configuration. The ONLY place that reads environment variables.

Secrets live in backend/.env (git-ignored). Copy backend/.env.example to
backend/.env and fill in OPENAI_API_KEY. In production (Render) set the same
names as environment variables instead - python-dotenv never overrides a
variable that is already set in the real environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.config import BASE_DIR

# override=False: real environment variables (Render) always win over .env.
load_dotenv(Path(BASE_DIR) / ".env", override=False)


def _str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    v = _str(name, "")
    if not v:
        return default
    return v.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ChatSettings:
    # --- OpenAI -----------------------------------------------------------
    api_key: str
    # Planner = question -> structured query plan. Accuracy-critical, small
    # output, so a fast model with minimal reasoning is the right trade-off.
    planner_model: str
    # Escalation model, used only if the planner's plan fails validation twice.
    planner_fallback_model: str
    # Narrator = verified numbers -> short prose. Cheap and fast.
    narrator_model: str
    # Empty string = do not send the parameter (models differ in what they
    # accept; omitting is always safe).
    planner_reasoning_effort: str
    narrator_reasoning_effort: str
    request_timeout_s: float
    sdk_max_retries: int
    planner_max_tokens: int     # completion budget (includes hidden reasoning tokens)
    narrator_max_tokens: int

    # --- Behaviour --------------------------------------------------------
    enabled: bool
    max_question_chars: int
    history_turns: int          # prior Q/A pairs given to the planner
    max_repairs: int            # re-asks of the planner after a validation error
    fuzzy_cutoff: float         # 0..1, entity matching strictness
    catalog_max_values: int     # list a dimension's values in the prompt up to this many
    max_limit: int              # hard cap for "top N"
    max_table_rows: int
    max_queries_per_plan: int
    max_measures: int           # per query

    # --- Performance / protection ------------------------------------------
    cache_size: int
    cache_ttl_s: int
    rate_limit_per_min: int     # per client IP; 0 disables

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@lru_cache(maxsize=1)
def get_settings() -> ChatSettings:
    return ChatSettings(
        api_key=_str("OPENAI_API_KEY"),
        planner_model=_str("OPENAI_PLANNER_MODEL", "gpt-6-luna"),
        planner_fallback_model=_str("OPENAI_PLANNER_FALLBACK_MODEL", "gpt-6.1-sol"),
        narrator_model=_str("OPENAI_NARRATOR_MODEL", "gpt-6-luna"),
        planner_reasoning_effort=_str("OPENAI_PLANNER_REASONING_EFFORT", "low"),
        narrator_reasoning_effort=_str("OPENAI_NARRATOR_REASONING_EFFORT", "low"),
        request_timeout_s=_float("OPENAI_TIMEOUT_S", 45.0),
        sdk_max_retries=_int("OPENAI_MAX_RETRIES", 2),
        planner_max_tokens=_int("OPENAI_PLANNER_MAX_TOKENS", 4000),
        narrator_max_tokens=_int("OPENAI_NARRATOR_MAX_TOKENS", 3000),
        enabled=_bool("CHAT_ENABLED", True),
        max_question_chars=_int("CHAT_MAX_QUESTION_CHARS", 600),
        history_turns=_int("CHAT_HISTORY_TURNS", 4),
        max_repairs=_int("CHAT_MAX_REPAIRS", 1),
        fuzzy_cutoff=_float("CHAT_FUZZY_CUTOFF", 0.84),
        catalog_max_values=_int("CHAT_CATALOG_MAX_VALUES", 30),
        max_limit=_int("CHAT_MAX_LIMIT", 50),
        max_table_rows=_int("CHAT_MAX_TABLE_ROWS", 200),
        max_queries_per_plan=_int("CHAT_MAX_QUERIES", 3),
        max_measures=_int("CHAT_MAX_MEASURES", 4),
        cache_size=_int("CHAT_CACHE_SIZE", 256),
        cache_ttl_s=_int("CHAT_CACHE_TTL_S", 3600),
        rate_limit_per_min=_int("CHAT_RATE_LIMIT_PER_MIN", 20),
    )
