"""
Narrative: the prose that accompanies the tables and charts.

Guarantee: no figure in the narrative was typed by a model.

  1. The narrator receives a numbered fact sheet and must quote values as
     {f3}-style placeholders. WE substitute the pre-formatted strings.
  2. Anything else it writes that contains a digit must already exist in the
     question, a label or the scope (e.g. "FY2027", "top 5"). Otherwise the
     text is rejected and the model is asked once to fix it.
  3. If the second attempt also fails (or the model is unreachable) we fall
     back to the deterministic sentences built in facts.py - slightly plainer,
     still correct. The user always gets a correct answer; the model only
     improves the wording.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.chat import semantic as sem
from app.chat.facts import Fact, FactSheet, placeholders_in, substitute
from app.chat.llm import LLMError
from app.chat.prompts import narrator_system_prompt, narrator_user_message
from app.chat.settings import ChatSettings

log = logging.getLogger("manipal.chat")

_DIGIT_RUN = re.compile(r"\d+(?:[.,]\d+)*")
_PLACEHOLDER = re.compile(r"\{f\d+\}")
# Every placeholder already carries its unit (₹ .. Cr, %, pp, days); typing one next to it would duplicate or contradict it.
_UNIT_TOKEN = re.compile(r"₹|%|\b(?:Cr|crores?|lakhs?)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Narration(BaseModel):
    """What the narrator model must return. Texts may contain {fN} placeholders."""
    headline: str = Field(description="One or two sentences that directly answer the question.")
    insights: list[str] = Field(description="0-3 short observations grounded in the facts or signals.")
    recommendations: list[str] = Field(description="0-2 concrete next actions grounded in the signals; empty if none are warranted.")
    follow_ups: list[str] = Field(description="2-3 short follow-up questions the user could ask next, phrased as the user would ask them.")


class NarrativeOut(BaseModel):
    """What the API returns (placeholders already replaced)."""
    headline: str
    insights: list[str]
    recommendations: list[str]
    follow_ups: list[str]
    source: str                     # "llm" | "fallback"


# ---------------------------------------------------------------------------
# Combining the fact sheets of several result blocks
# ---------------------------------------------------------------------------
class CombinedFacts:
    """Several FactSheets under one namespace so one narration covers the whole answer."""

    def __init__(self, parts: list[tuple[str, FactSheet]]):
        self.parts: list[tuple[str, FactSheet]] = []
        self.facts: dict[str, Fact] = {}
        offset = 0
        for title, sheet in parts:
            renum, offset = _renumber(sheet, offset)
            self.parts.append((title, renum))
            self.facts.update(renum.facts)

    # -- for the prompt ---------------------------------------------------
    def render_for_llm(self) -> str:
        if len(self.parts) == 1:
            return self.parts[0][1].render_for_llm()
        blocks = []
        for i, (title, sh) in enumerate(self.parts, 1):
            blocks.append(f"=== ANSWER PART {i}: {title} ===\n{sh.render_for_llm()}")
        return "\n\n".join(blocks)

    # -- digit tokens that may legitimately appear as plain text ----------
    def allowed_digit_runs(self, *extra: str) -> set[str]:
        runs: set[str] = set()
        for _, sh in self.parts:
            for lit in sh.literals:
                runs.update(_DIGIT_RUN.findall(lit))
            for c in sh.context:
                runs.update(_DIGIT_RUN.findall(c))
            for f in sh.facts.values():          # labels only, never display values
                runs.update(_DIGIT_RUN.findall(f.label))
        for e in extra:
            runs.update(_DIGIT_RUN.findall(e or ""))
        return runs

    # -- deterministic text ------------------------------------------------
    def fallback_sentences(self) -> tuple[str, list[str]]:
        heads, rest = [], []
        for _, sh in self.parts:
            subs = [sh.substitute(s) for s in sh.sentences]
            if subs:
                heads.append(subs[0])
                rest += subs[1:]
            rest += [sh.substitute(s) for s in sh.signals]
        headline = " ".join(heads) if heads else "Here are the results."
        return headline, rest


def _renumber(sheet: FactSheet, offset: int) -> tuple[FactSheet, int]:
    mapping: dict[str, str] = {}
    out = FactSheet(context=list(sheet.context), literals=set(sheet.literals))
    n = offset
    for fid, f in sheet.facts.items():
        n += 1
        nid = f"f{n}"
        mapping[fid] = nid
        out.facts[nid] = Fact(nid, f.label, f.display, f.raw)

    def remap(text: str) -> str:
        return re.sub(r"\{(f\d+)\}", lambda m: "{" + mapping.get(m.group(1), m.group(1)) + "}", text)

    out.signals = [remap(s) for s in sheet.signals]
    out.sentences = [remap(s) for s in sheet.sentences]
    out._n = n
    return out, n


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def _texts(n: Narration) -> list[str]:
    return [n.headline, *n.insights, *n.recommendations, *n.follow_ups]


def verify(n: Narration, combined: CombinedFacts, allowed_runs: set[str]) -> list[str]:
    """Return a list of problems (empty = the narration is safe to show)."""
    problems: list[str] = []
    if not n.headline.strip():
        problems.append("The headline is empty.")
    prose = {id(t) for t in [n.headline, *n.insights, *n.recommendations]}
    for t in _texts(n):
        for pid in placeholders_in(t):
            if pid not in combined.facts:
                problems.append(f"Unknown placeholder {{{pid}}}.")
        bare = _PLACEHOLDER.sub(" ", t)
        if id(t) in prose and _UNIT_TOKEN.search(bare):
            problems.append(f"Units/currency symbols must come from the placeholder, not your text: \"{t[:80]}\".")
        bad = sorted({r for r in _DIGIT_RUN.findall(bare) if r not in allowed_runs})
        if bad:
            problems.append(f"Typed number(s) {', '.join(bad)} in: \"{t[:80]}\". Quote values only as {{fN}} placeholders.")
    return problems


def render(n: Narration, combined: CombinedFacts) -> NarrativeOut:
    sub = lambda t: substitute(t.strip(), combined.facts)       # noqa: E731
    return NarrativeOut(
        headline=sub(n.headline),
        insights=[sub(t) for t in n.insights if t.strip()][:3],
        recommendations=[sub(t) for t in n.recommendations if t.strip()][:2],
        follow_ups=[t.strip() for t in n.follow_ups if t.strip()][:3],
        source="llm",
    )


# ---------------------------------------------------------------------------
# Deterministic follow-up suggestions (used when the model's are unavailable)
# ---------------------------------------------------------------------------
_PAREN = re.compile(r"\s*\([^)]*\)")


def plain_label(label: str) -> str:
    """'SOB compliance (%)' -> 'SOB compliance' (acronyms keep their case)."""
    s = _PAREN.sub("", label).strip()
    first = s.split(" ")[0]
    return s if (first.isupper() or len(first) < 2) else s[0].lower() + s[1:]


def default_follow_ups(queries: list, limit: int = 3) -> list[str]:
    """Suggestions derived from the registry: unused default breakdowns, trend, comparison."""
    if not queries:
        return []
    q = queries[0]
    m = next((x for x in q.measures if x.id == q.sort_by), q.measures[0])
    name = plain_label(m.label)
    out: list[str] = []
    if q.grain == "none":
        out.append(f"Show {name} month by month")
    for d in m.default_dims:
        dim = sem.DIMENSIONS[d]
        if d in q.group_dims or not sem.dimension_supported_on(dim, q.tables):
            continue
        out.append(f"Break {name} down by {plain_label(dim.label)}")
        break
    if not q.compare_previous and q.grain == "none" and q.period.unit:
        out.append(f"How does {name} compare with the previous period?")
    return out[:limit]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def fallback_narrative(combined: CombinedFacts, queries: list) -> NarrativeOut:
    headline, rest = combined.fallback_sentences()
    return NarrativeOut(headline=headline, insights=rest[:4], recommendations=[],
                        follow_ups=default_follow_ups(queries), source="fallback")


async def build_narrative(llm, settings: ChatSettings, question: str, combined: CombinedFacts,
                          queries: list) -> NarrativeOut:
    """Ask the narrator, verify, retry once with feedback, else fall back."""
    system = narrator_system_prompt()
    user = narrator_user_message(question, combined.render_for_llm())
    extra = [question] + [str(q.limit) for q in queries if q.limit]
    allowed = combined.allowed_digit_runs(*extra)
    messages = [{"role": "user", "content": user}]
    last: Optional[Narration] = None

    for attempt in range(2):
        try:
            last = await llm.narrate(system, messages)
        except LLMError as e:
            log.warning("narrator unavailable (%s): %s", e.kind, e)
            break
        problems = verify(last, combined, allowed)
        if not problems:
            out = render(last, combined)
            if not out.follow_ups:
                out.follow_ups = default_follow_ups(queries)
            return out
        log.info("narration rejected (attempt %d): %s", attempt + 1, problems)
        messages = messages + [
            {"role": "assistant", "content": last.model_dump_json()},
            {"role": "user", "content": "Rejected: " + " ".join(problems[:4])
             + " Rewrite the whole answer, quoting every value as a {fN} placeholder and typing no other numbers."},
        ]
    return fallback_narrative(combined, queries)
