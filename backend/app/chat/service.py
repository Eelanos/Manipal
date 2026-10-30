"""
The orchestrator: question -> plan -> validated query -> numbers -> charts -> words.

    1. PLAN      the planner model turns the question into a structured Plan
                 (closed enums, validated). Invalid plans are sent back once with
                 the exact error; a stronger fallback model is tried if that fails.
    2. RESOLVE   filter values are matched to real data values; periods become
                 exact dates. Entities that do not exist produce "did you mean".
    3. EXECUTE   pandas computes every figure (engine.py), in parallel threads.
    4. PRESENT   KPIs / charts / table are built by rules (present.py).
    5. NARRATE   the narrator writes prose over a numbered fact sheet; numbers are
                 substituted by us and verified (narrative.py).

Results are streamed as server-sent events, so charts and tables appear as soon
as they are computed - before the narration has been written.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import AsyncIterator, Optional

from pydantic import BaseModel, Field

from app.chat import prompts
from app.chat import semantic as sem
from app.chat.catalog import Catalog, get_catalog
from app.chat.engine import execute
from app.chat.facts import build_facts
from app.chat.llm import LLM, USER_MESSAGES, LLMError
from app.chat.narrative import (CombinedFacts, build_narrative, fallback_narrative,
                                plain_label)
from app.chat.present import build_block
from app.chat.resolver import ResolvedQuery, resolve_query
from app.chat.settings import ChatSettings, get_settings
from app.chat.spec import Plan, parse_query_spec
from app.chat.timeparse import PlanError
from app.chat.util import TTLCache
from app.data_loader import get_store

log = logging.getLogger("manipal.chat")


# ---------------------------------------------------------------------------
# Request model (what the router accepts)
# ---------------------------------------------------------------------------
class HistoryTurn(BaseModel):
    question: str = Field(max_length=1000)
    specs: list[dict] = Field(default_factory=list, max_length=5)
    answer: str = Field("", max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(max_length=5000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=50)


# ---------------------------------------------------------------------------
# Planning outcome
# ---------------------------------------------------------------------------
@dataclass
class Planned:
    queries: list = field(default_factory=list)          # list[ResolvedQuery]
    notes: list = field(default_factory=list)
    # when there is nothing to run:
    kind: Optional[str] = None                           # clarify | out_of_scope | chat | not_found | failed
    text: str = ""


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip())


def _sha(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


class ChatService:
    def __init__(self, settings: Optional[ChatSettings] = None, llm: Optional[LLM] = None):
        self.s = settings or get_settings()
        self.llm = llm or LLM(self.s)
        self.plan_cache = TTLCache(self.s.cache_size, self.s.cache_ttl_s)
        self.narr_cache = TTLCache(self.s.cache_size, self.s.cache_ttl_s)

    # ------------------------------------------------------------------ history
    def _clean_history(self, history: list[HistoryTurn]) -> list[dict]:
        out = []
        for h in history[-self.s.history_turns:]:
            specs = []
            for raw in h.specs:
                spec = parse_query_spec(raw)
                if spec is not None:
                    specs.append(spec.model_dump(mode="json", exclude_none=True))
            out.append({"question": _norm(h.question)[:self.s.max_question_chars],
                        "specs": specs, "answer": _norm(h.answer)[:300]})
        return out

    # ------------------------------------------------------------------ planning
    def _resolve_all(self, plan: Plan, cat: Catalog) -> tuple[list[ResolvedQuery], list[PlanError]]:
        resolved, errors, seen = [], [], set()
        for spec in plan.queries:
            key = spec.model_dump_json()
            if key in seen:
                continue
            seen.add(key)
            try:
                resolved.append(resolve_query(spec, cat, self.s))
            except PlanError as e:
                errors.append(e)
        return resolved, errors

    def _from_plan(self, plan: Plan, cat: Catalog) -> tuple[Optional[Planned], list[PlanError]]:
        """Turn a Plan into a Planned outcome, or the validation errors that blocked it."""
        if plan.action != "query":
            default = {"clarify": "Could you tell me a little more about what you'd like to see?",
                       "out_of_scope": "That isn't something this dataset can answer.",
                       "chat": "I can answer questions about Manipal's pharmacy and inventory data."}
            return Planned(kind=plan.action, text=(plan.message or default[plan.action]).strip()), []
        if not plan.queries:
            return None, [PlanError("The plan contained no queries.")]
        notes: list[str] = []
        queries = plan.queries
        if len(queries) > self.s.max_queries_per_plan:
            notes.append(f"Your question needed {len(queries)} analyses; showing the first {self.s.max_queries_per_plan}.")
            plan = plan.model_copy(update={"queries": queries[:self.s.max_queries_per_plan]})
        resolved, errors = self._resolve_all(plan, cat)
        if errors:
            return None, errors
        return Planned(queries=resolved, notes=notes), []

    async def _plan(self, question: str, history: list[dict], cat: Catalog) -> tuple[Planned, bool]:
        """Returns (planned, from_cache)."""
        key = _sha(_norm(question).lower(), json.dumps(history, sort_keys=True))
        cached = self.plan_cache.get(key)
        if cached is not None:
            planned, _ = self._from_plan(cached, cat)
            if planned is not None:
                return planned, True

        system = prompts.planner_system_prompt()
        messages = [{"role": "user", "content": prompts.planner_user_message(question, history)}]
        models = [self.s.planner_model]
        if self.s.planner_fallback_model and self.s.planner_fallback_model not in models:
            models.append(self.s.planner_fallback_model)

        last_errors: list[PlanError] = []
        last_llm_error: Optional[LLMError] = None
        for mi, model in enumerate(models):
            repairs = 0
            while True:
                try:
                    plan = await self.llm.plan(system, messages, model)
                except LLMError as e:
                    last_llm_error = e
                    # A model the key cannot use, or a malformed answer: try the next model.
                    if e.kind in ("model_unavailable", "bad_output") and mi + 1 < len(models):
                        break
                    raise
                planned, errors = self._from_plan(plan, cat)
                if planned is not None:
                    self.plan_cache.put(key, plan)
                    return planned, False
                last_errors = errors
                # "X not found - did you mean ..." is about the user's data, not a planner slip.
                if all(e.suggestions for e in errors):
                    return Planned(kind="not_found", text=_not_found_text(errors)), False
                if repairs < self.s.max_repairs:
                    repairs += 1
                    messages = messages + [
                        {"role": "assistant", "content": plan.model_dump_json(exclude_none=True)},
                        {"role": "user", "content": prompts.repair_message([e.message for e in errors])}]
                    continue
                break                                  # escalate to the next model
        if last_errors:
            return Planned(kind="failed", text="I couldn't turn that into a query I can run reliably ("
                           + "; ".join(e.message for e in last_errors[:2])
                           + "). Could you rephrase it, or name the measure and period you want?"), False
        raise last_llm_error or LLMError("upstream", USER_MESSAGES["upstream"])

    # ------------------------------------------------------------------ execution
    def _run_one(self, rq: ResolvedQuery, idx: int):
        store, cat = get_store(), get_catalog()
        rs = execute(store, cat, rq, self.s.max_table_rows)
        return rs, build_block(rs, store, f"b{idx + 1}"), build_facts(rs, store)

    # ------------------------------------------------------------------ main entry
    async def stream(self, req: ChatRequest) -> AsyncIterator[dict]:
        """Yield {"event": name, "data": dict} items for the SSE layer."""
        rid, t0 = uuid.uuid4().hex[:8], time.perf_counter()
        ms: dict = {}
        question = _norm(req.question)

        if not self.s.enabled:
            yield _err("disabled", "The assistant is switched off on this server."); return
        if not question:
            yield _err("empty", "Please type a question."); return
        if len(question) > self.s.max_question_chars:
            yield _err("too_long", f"Please keep the question under {self.s.max_question_chars} characters."); return
        if not self.s.configured:
            yield _err("not_configured", USER_MESSAGES["not_configured"]); return

        try:
            cat = get_catalog()
            log.info("[%s] question: %s", rid, question[:200])
            yield _ev("status", stage="planning", text="Understanding your question…")
            planned, cached = await self._plan(question, self._clean_history(req.history), cat)
            ms["plan"] = _since(t0)

            if planned.kind:
                log.info("[%s] %s", rid, planned.kind)
                yield _ev("message", kind=planned.kind, text=planned.text)
                yield _ev("done", ms=ms, cached=cached)
                return

            yield _ev("status", stage="computing", text="Crunching the numbers…")
            t1 = time.perf_counter()
            results = await asyncio.gather(*[asyncio.to_thread(self._run_one, rq, i)
                                             for i, rq in enumerate(planned.queries)])
            ms["compute"] = _since(t1)

            blocks = []
            for i, (rs, block, sheet) in enumerate(results):
                if i == 0 and planned.notes:
                    block.notes = list(dict.fromkeys(planned.notes + block.notes))
                blocks.append(block)
                yield _ev("result", block=block.model_dump(mode="json"))

            # --- narration -------------------------------------------------------
            parts = [(rs.query.title, sheet) for rs, _, sheet in results]
            combined = CombinedFacts(parts)
            queries = [rs.query for rs, _, _ in results]
            if all(b.empty for b in blocks):
                narr = fallback_narrative(combined, queries)
                narr.follow_ups = []
            else:
                yield _ev("status", stage="writing", text="Writing the summary…")
                t2 = time.perf_counter()
                nkey = _sha(question.lower(), combined.render_for_llm())
                narr = self.narr_cache.get(nkey)
                if narr is None:
                    narr = await build_narrative(self.llm, self.s, question, combined, queries)
                    if narr.source == "llm":                       # never cache a degraded answer
                        self.narr_cache.put(nkey, narr)
                ms["narrate"] = _since(t2)
            yield _ev("narrative", **narr.model_dump())
            ms["total"] = _since(t0)
            log.info("[%s] done %s", rid, ms)
            yield _ev("done", ms=ms, cached=cached)

        except LLMError as e:
            log.warning("[%s] LLM error %s: %s", rid, e.kind, e)
            yield _err(e.kind, USER_MESSAGES.get(e.kind, str(e)))
        except PlanError as e:
            yield _err("plan", e.message)
        except Exception:
            log.exception("[%s] unexpected failure", rid)
            yield _err("internal", f"Something went wrong while answering that (ref {rid}). Please try again.")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ev(name: str, **data) -> dict:
    return {"event": name, "data": data}


def _err(kind: str, text: str) -> dict:
    return _ev("error", kind=kind, text=text)


def _since(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)


def _not_found_text(errors: list[PlanError]) -> str:
    lines = []
    for e in errors[:2]:
        lines.append(e.message)
        if e.suggestions and not any(s in e.message for s in e.suggestions[:1]):
            lines.append("Closest matches: " + ", ".join(e.suggestions[:5]) + ".")
    return " ".join(lines)


@lru_cache(maxsize=1)
def get_service() -> ChatService:
    return ChatService()


# ---------------------------------------------------------------------------
# Starter questions - generated from the registry (nothing hand-written)
# ---------------------------------------------------------------------------
def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def build_suggestions(cat: Catalog, limit: int = 8) -> list[str]:
    """Clickable starter questions, derived from the registry's featured measures."""
    items: list[str] = []
    featured = [m for m in sem.MEASURES.values() if m.featured]
    for m in featured:
        name = plain_label(m.label)
        dim = next((sem.DIMENSIONS[d] for d in m.default_dims
                    if d in sem.DIMENSIONS and sem.dimension_supported_on(sem.DIMENSIONS[d], sem.measure_tables(m))), None)
        if sem.is_point_in_time(m):
            items.append(f"Current {name} by {plain_label(dim.label)}" if dim else f"What is the current {name}?")
        elif dim:
            items.append(f"{_cap(name)} by {plain_label(dim.label)} this fiscal year")
        else:
            items.append(f"What is the {name} this fiscal year?")
    extras: list[str] = []
    flow = [m for m in featured if not sem.is_point_in_time(m)]
    if flow:
        extras.append(f"Monthly trend of {plain_label(flow[0].label)}")
    if len(flow) > 1:
        extras.append(f"{_cap(plain_label(flow[1].label))} this fiscal year vs last year")
    return items[:max(0, limit - len(extras))] + extras
