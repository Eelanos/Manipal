"""
Run ONCE by hand after putting OPENAI_API_KEY in backend/.env:

    cd backend
    python tests/live_smoke.py

It sends real questions through the whole pipeline (real planner + narrator) and
prints what each one produced, so you can see the models are reachable, the plans
validate, and the answers read well. It never changes any data.
Exit code 1 if any question errored or fell back to the deterministic narration.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chat.service import ChatRequest, ChatService          # noqa: E402
from app.chat.settings import get_settings                      # noqa: E402

QUESTIONS = [
    "What is our total consumption this fiscal year?",
    "Show consumption by department for FY2026",
    "Which 5 doctors have the biggest switchable opportunity?",
    "How has formulary compliance trended month by month this year?",
    "Compare SOB compliance this fiscal year with last year",
    "Current stock by ageing bucket",
    "Which vendors have the most purchase orders in transit?",
    "Budget utilisation by department for Pune",
    "What share of consumption is implants vs non-implants?",
    "inventory days by department",
    "show compliance",                                   # ambiguous -> should ask
    "What is the patient satisfaction score?",           # out of scope
    "Consumption in Cardiolgy last quarter",             # typo + relative period
]


async def main() -> int:
    s = get_settings()
    if not s.configured:
        print("OPENAI_API_KEY is not set (backend/.env). Nothing to test.")
        return 1
    svc = ChatService(s)
    print(f"planner={s.planner_model}  fallback={s.planner_fallback_model}  narrator={s.narrator_model}\n")
    for m in dict.fromkeys([s.planner_model, s.planner_fallback_model, s.narrator_model]):
        err = await svc.llm.ping(m)
        print(f"  model {m}: {'ok' if err is None else 'PROBLEM -> ' + err}")
    print()

    problems = 0
    for q in QUESTIONS:
        t0 = time.perf_counter()
        events = [e async for e in svc.stream(ChatRequest(question=q))]
        secs = time.perf_counter() - t0
        print(f"Q: {q}   ({secs:.1f}s)")
        for e in events:
            name, d = e["event"], e["data"]
            if name == "result":
                b = d["block"]
                rows = len(b["table"]["rows"]) if b["table"] else 0
                print(f"   result  : {b['title']} | {' · '.join(b['scope'])} | kpis={len(b['kpis'])} charts={len(b['charts'])} rows={rows}")
                for n in b["notes"]:
                    print(f"             note: {n}")
            elif name == "narrative":
                print(f"   answer  : {d['headline']}")
                for t in d["insights"]:
                    print(f"             - {t}")
                for t in d["recommendations"]:
                    print(f"             next: {t}")
                if d["source"] != "llm":
                    print("   !! narration fell back to deterministic text"); problems += 1
            elif name == "message":
                print(f"   {d['kind']:8}: {d['text']}")
            elif name == "error":
                print(f"   !! ERROR {d['kind']}: {d['text']}"); problems += 1
        print()
    print("OK" if not problems else f"{problems} problem(s) - see the lines marked !!")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
