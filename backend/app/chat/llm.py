"""
The only module that talks to OpenAI.

* Structured Outputs: `chat.completions.parse(response_format=<pydantic model>)`
  makes the API itself enforce the plan/narration schema.
* Errors are mapped to a small set of kinds (LLMError.kind) so the service can
  show a precise, honest message instead of a stack trace.
* Every call logs model, latency and token usage.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from pydantic import BaseModel

from app.chat.settings import ChatSettings

log = logging.getLogger("manipal.chat")


class LLMError(Exception):
    """kind: not_installed | not_configured | auth | rate_limit | timeout | model_unavailable | bad_output | upstream"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


USER_MESSAGES = {
    "not_installed": "The OpenAI SDK is not installed on the server. Run `python -m pip install -r requirements.txt` in the backend and restart.",
    "not_configured": "The assistant is not configured yet: OPENAI_API_KEY is missing on the server.",
    "auth": "The OpenAI API key was rejected. Please check OPENAI_API_KEY on the server.",
    "rate_limit": "The AI service is rate-limited right now. Please try again in a moment.",
    "timeout": "The AI service took too long to respond. Please try again.",
    "model_unavailable": "The configured AI model is not available for this API key. Check OPENAI_PLANNER_MODEL on the server.",
    "bad_output": "The AI service returned an answer I could not use. Please rephrase the question and try again.",
    "upstream": "The AI service is temporarily unavailable. Please try again.",
}


def _import_openai():
    """Import the SDK lazily (the app boots without it) with an actionable error if it is missing."""
    try:
        import openai
    except ImportError as e:
        raise LLMError("not_installed", USER_MESSAGES["not_installed"]) from e
    return openai


class LLM:
    def __init__(self, settings: ChatSettings):
        self.s = settings
        self._client = None
        # Models that rejected `reasoning_effort`: we stop sending it for them.
        self._no_effort: set[str] = set()

    # -- client ------------------------------------------------------------
    def _get_client(self):
        if not self.s.api_key:
            raise LLMError("not_configured", USER_MESSAGES["not_configured"])
        if self._client is None:
            self._client = _import_openai().AsyncOpenAI(api_key=self.s.api_key, timeout=self.s.request_timeout_s,
                                       max_retries=self.s.sdk_max_retries)
        return self._client

    # -- core call ---------------------------------------------------------
    async def _parse(self, *, model: str, system: str, messages: list[dict], schema: type[BaseModel],
                     effort: str, max_tokens: int, cache_key: str, tag: str):
        openai = _import_openai()
        client = self._get_client()
        kwargs = dict(model=model,
                      messages=[{"role": "system", "content": system}, *messages],
                      response_format=schema,
                      max_completion_tokens=max_tokens,
                      prompt_cache_key=cache_key)
        if effort and model not in self._no_effort:
            kwargs["reasoning_effort"] = effort
        t0 = time.perf_counter()
        for attempt in (1, 2):
            try:
                resp = await client.chat.completions.parse(**kwargs)
                break
            except openai.BadRequestError as e:
                # A model that does not support reasoning_effort: retry once without it.
                if "reasoning_effort" in kwargs and "reasoning" in str(e).lower() and attempt == 1:
                    self._no_effort.add(model)
                    kwargs.pop("reasoning_effort", None)
                    continue
                raise LLMError("upstream", f"{tag}: bad request: {e}") from e
            except openai.AuthenticationError as e:
                raise LLMError("auth", USER_MESSAGES["auth"]) from e
            except openai.PermissionDeniedError as e:
                raise LLMError("model_unavailable", USER_MESSAGES["model_unavailable"]) from e
            except openai.NotFoundError as e:
                raise LLMError("model_unavailable", USER_MESSAGES["model_unavailable"]) from e
            except openai.RateLimitError as e:
                raise LLMError("rate_limit", USER_MESSAGES["rate_limit"]) from e
            except openai.APITimeoutError as e:
                raise LLMError("timeout", USER_MESSAGES["timeout"]) from e
            except openai.APIConnectionError as e:
                raise LLMError("upstream", USER_MESSAGES["upstream"]) from e
            except openai.APIStatusError as e:
                raise LLMError("upstream", USER_MESSAGES["upstream"]) from e
            except Exception as e:                       # schema/parse failures inside the SDK
                raise LLMError("bad_output", USER_MESSAGES["bad_output"]) from e
        ms = (time.perf_counter() - t0) * 1000
        u = getattr(resp, "usage", None)
        log.info("llm %s model=%s %.0fms prompt=%s cached=%s completion=%s", tag, model, ms,
                 getattr(u, "prompt_tokens", "?"),
                 getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", "?"),
                 getattr(u, "completion_tokens", "?"))
        msg = resp.choices[0].message
        if getattr(msg, "refusal", None):
            raise LLMError("bad_output", USER_MESSAGES["bad_output"])
        if msg.parsed is None:
            raise LLMError("bad_output", USER_MESSAGES["bad_output"])
        return msg.parsed

    # -- public ------------------------------------------------------------
    async def plan(self, system: str, messages: list[dict], model: Optional[str] = None):
        from app.chat.spec import Plan
        return await self._parse(model=model or self.s.planner_model, system=system, messages=messages,
                                 schema=Plan, effort=self.s.planner_reasoning_effort,
                                 max_tokens=self.s.planner_max_tokens, cache_key="manipal-planner", tag="plan")

    async def narrate(self, system: str, messages: list[dict]):
        from app.chat.narrative import Narration
        return await self._parse(model=self.s.narrator_model, system=system, messages=messages,
                                 schema=Narration, effort=self.s.narrator_reasoning_effort,
                                 max_tokens=self.s.narrator_max_tokens, cache_key="manipal-narrator", tag="narrate")

    async def ping(self, model: str) -> Optional[str]:
        """Cheap availability check for /health?deep=1. Returns None if OK, else a short error."""
        try:
            client = self._get_client()
            # Reasoning models spend completion tokens on thinking, so a tiny cap fails with
            # "output limit reached" even though the model works. Give it room.
            await client.chat.completions.create(model=model, max_completion_tokens=1024,
                                                 messages=[{"role": "user", "content": "Reply with: ok"}])
            return None
        except LLMError as e:
            return str(e)
        except Exception as e:
            return f"{type(e).__name__}: {str(e)[:160]}"
