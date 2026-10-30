"""
HTTP surface of the chat feature (mounted by app/main.py, additive only).

    POST /api/chat              question (+ history) -> server-sent events
    GET  /api/chat/suggestions  starter questions generated from the registry
    GET  /api/chat/health       config + registry check; ?deep=true also pings the models

SSE events (each `event: <name>` + one JSON `data:` line):
    status     {stage, text}                 progress while working
    result     {block}                       one table/chart block (ResultBlock)
    narrative  {headline, insights, recommendations, follow_ups, source}
    message    {kind, text}                  clarify / out_of_scope / chat / not_found / failed
    error      {kind, text}
    done       {ms, cached}                  always the last event
"""

from __future__ import annotations

import asyncio
import json
import importlib.util
import math
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.chat.catalog import get_catalog
from app.chat.service import ChatRequest, build_suggestions, get_service
from app.chat.settings import get_settings
from app.chat.util import RateLimiter

router = APIRouter(prefix="/api/chat", tags=["chat"])
_limiter = RateLimiter(get_settings().rate_limit_per_min)


def _clean(o: Any) -> Any:
    """JSON-safe: NaN/Inf -> null (the browser's JSON.parse rejects them)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(_clean(data), ensure_ascii=False, default=str)}\n\n"


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("")
async def chat(req: ChatRequest, request: Request):
    if not _limiter.allow(_client_key(request)):
        return JSONResponse({"detail": "Too many questions in a short time. Please wait a moment."},
                            status_code=429)
    service = get_service()

    async def gen():
        yield ": open\n\n"                                   # flush headers immediately
        try:
            async for item in service.stream(req):
                yield _sse(item["event"], item["data"])
        except asyncio.CancelledError:                       # client went away
            raise

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",                           # stop nginx/Render from buffering the stream
    })


@router.get("/suggestions")
def suggestions():
    cat = get_catalog()
    return {"suggestions": build_suggestions(cat),
            "data": {"from": cat.data_start.isoformat(), "to": cat.data_end.isoformat(),
                     "as_of": cat.as_of.isoformat()}}


@router.get("/health")
async def health(deep: bool = False):
    s, cat = get_settings(), get_catalog()
    out: dict = {
        "enabled": s.enabled,
        "configured": s.configured,
        "sdk_installed": importlib.util.find_spec("openai") is not None,
        "models": {"planner": s.planner_model, "planner_fallback": s.planner_fallback_model,
                   "narrator": s.narrator_model},
        "registry_problems": cat.problems,
        "data": {"from": cat.data_start.isoformat(), "to": cat.data_end.isoformat(),
                 "as_of": cat.as_of.isoformat()},
    }
    if deep and s.configured:
        llm = get_service().llm
        names = list(dict.fromkeys([s.planner_model, s.planner_fallback_model, s.narrator_model]))
        results = await asyncio.gather(*[llm.ping(n) for n in names])
        out["model_check"] = {n: (r or "ok") for n, r in zip(names, results)}
    models_ok = all(v == "ok" for v in out.get("model_check", {}).values())
    out["status"] = "ok" if models_ok and s.enabled and s.configured and out["sdk_installed"] and not cat.problems else "degraded"
    return out
