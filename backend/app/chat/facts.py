"""
Facts: every number the narrator may mention, computed by us.

The narrator model never types a figure. It receives a numbered fact sheet
("[f3] Highest department: Cardiology - Consumption value = ₹16.69 Cr") and
writes prose with {f3}-style placeholders, which we replace with the exact
pre-formatted strings. Anything it writes that is not a placeholder and
contains a digit is rejected (see narrative.py). That is what makes "accurate
numbers" a structural guarantee rather than a hope.

Signals are rule-based observations tied to benchmarks that exist in config
(formulary target, budget = 100%). No threshold is invented here.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from app.chat import semantic as sem
from app.chat.engine import ResultSet
from app.chat.present import fmt_delta, fmt_value
from app.chat.resolver import is_additive


@dataclass
class Fact:
    id: str
    label: str
    display: str
    raw: Optional[float] = None


@dataclass
class FactSheet:
    facts: dict = field(default_factory=dict)
    context: list = field(default_factory=list)       # plain-language scope lines
    signals: list = field(default_factory=list)       # sentences (placeholders allowed)
    sentences: list = field(default_factory=list)     # deterministic fallback prose
    literals: set = field(default_factory=set)        # strings allowed to contain digits
    _n: int = 0

    def add(self, label: str, display: str, raw: Optional[float] = None) -> str:
        """Register a fact and return its placeholder, e.g. '{f4}'."""
        self._n += 1
        fid = f"f{self._n}"
        self.facts[fid] = Fact(fid, label, display, raw)
        return "{" + fid + "}"

    def lit(self, *items) -> None:
        for i in items:
            if i:
                self.literals.add(str(i))

    # -- rendering ----------------------------------------------------------
    def render_for_llm(self) -> str:
        out = ["CONTEXT"]
        out += [f"- {c}" for c in self.context]
        out.append("FACTS (use the {id} placeholder to quote a value; never type the number)")
        out += [f"[{f.id}] {f.label} = {f.display}" for f in self.facts.values()]
        if self.signals:
            out.append("SIGNALS (rule-based; you may rephrase, keep placeholders)")
            out += [f"- {s}" for s in self.signals]
        return "\n".join(out)

    def substitute(self, text: str) -> str:
        return substitute(text, self.facts)

    def fallback_text(self) -> str:
        return " ".join(self.substitute(s) for s in self.sentences)


_PLACEHOLDER = re.compile(r"\{(f\d+)\}")


def substitute(text: str, facts: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: facts[m.group(1)].display if m.group(1) in facts else m.group(0), text)


def placeholders_in(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _lc(label: str) -> str:
    """Lower-case the first word for mid-sentence use, but leave acronyms (SOB, IP) alone."""
    first = label.split(" ")[0]
    return label if (first.isupper() or len(first) < 2) else label[0].lower() + label[1:]


def _move(v: float, high: bool) -> str:
    """Honest name for the largest/smallest change: 'rise' only if it really rose."""
    if high:
        return "rise" if v > 0 else ("smallest fall" if v < 0 else "no change")
    return "fall" if v < 0 else ("smallest rise" if v > 0 else "no change")


def _valid(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def build_facts(rs: ResultSet, store) -> FactSheet:
    q, df = rs.query, rs.df
    sh = FactSheet()
    sh.context.append(f"Period: {q.period.label}")
    for f in q.filters:
        sh.context.append(f"Filter: {sem.DIMENSIONS[f.dim_id].label} {'excluding ' if f.op == 'not_in' else '= '}"
                          + ", ".join(f.labels))
    if q.group_dims:
        sh.context.append("Broken down by: " + ", ".join(sem.DIMENSIONS[d].label for d in q.group_dims))
    if q.grain != "none":
        sh.context.append(f"Time grain: {q.grain.replace('_', ' ')}")
    for n in rs.notes:
        sh.context.append(f"Note: {n}")
    sh.lit(q.period.label, *[l for f in q.filters for l in f.labels], *rs.notes)
    sh.lit(*[m.label for m in q.measures])
    for d in q.group_dims:
        if d in df:
            sh.lit(*df[d].astype(str).unique())
    if "_period" in df:
        sh.lit(*df["_period"].astype(str).unique())

    if rs.empty:
        sh.sentences.append(rs.empty_reason or "No data matches that selection.")
        return sh

    primary = next(m for m in q.measures if m.id == q.sort_by)

    if not q.group_dims and q.grain == "none":
        _scalar(sh, rs, store)
    elif not q.group_dims:
        _trend(sh, rs, primary)
    elif q.grain == "none" and len(q.group_dims) == 1:
        _breakdown(sh, rs, primary, store)
    elif q.grain != "none":
        _breakdown_over_time(sh, rs, primary)
    else:
        _two_dims(sh, rs, primary)

    # Secondary measures: overall figure only (their detail is in the table).
    if q.group_dims or q.grain != "none":
        for m in q.measures:
            if m.id != primary.id and _valid(rs.totals.get(m.id)):
                ph = sh.add(f"{m.label} (overall)", fmt_value(rs.totals[m.id], m.unit), rs.totals[m.id])
                sh.sentences.append(f"Overall {_lc(m.label)} is {ph}.")
    if q.group_dims or q.grain != "none":
        _threshold_signals(sh, rs, primary, store)
    return sh


# -- scalar -------------------------------------------------------------------
def _scalar(sh: FactSheet, rs: ResultSet, store) -> None:
    q = rs.query
    for m in q.measures:
        v = rs.totals.get(m.id)
        if not _valid(v):
            sh.sentences.append(f"{m.label} has no value for {q.period.label} (the denominator is zero).")
            sh.context.append(f"{m.label}: no value (undefined for this selection)")
            continue
        when = ""
        if sem.is_point_in_time(m) and rs.snapshot_dates:
            snaps = [d for ds in rs.snapshot_dates.values() for d in ds]
            if snaps:
                when = f" as on {max(snaps):%d %b %Y}"
        ph = sh.add(f"{m.label}{when}", fmt_value(v, m.unit), v)
        sh.sentences.append(f"{m.label}{when} for {q.period.label} is {ph}.")
        if rs.prior_totals is not None and _valid(rs.prior_totals.get(m.id)):
            pv = rs.prior_totals[m.id]
            ph_p = sh.add(f"{m.label} in the previous period ({rs.prior_period.label})", fmt_value(pv, m.unit), pv)
            ph_d = sh.add(f"Change in {m.label} vs previous period", fmt_delta(v - pv, m.unit), v - pv)
            sh.sentences.append(f"That compares with {ph_p} in {rs.prior_period.label} ({ph_d}).")
            if m.unit not in ("percent", "days") and pv:
                ph_pc = sh.add(f"% change in {m.label} vs previous period",
                               fmt_delta((v - pv) / abs(pv) * 100, "percent").replace(" pp", "%"),
                               (v - pv) / abs(pv) * 100)
                sh.signals.append(f"{m.label} moved {ph_pc} versus the previous period.")
        _scalar_threshold(sh, m, v, store)


def _scalar_threshold(sh: FactSheet, m: sem.Measure, v: float, store) -> None:
    th = m.threshold
    if th is None:
        return
    ref = sem.resolve_ref(th.value, store) if isinstance(th.value, sem.Ref) else th.value
    ph_ref = sh.add(th.label.capitalize(), fmt_value(ref, m.unit), ref)
    gap = v - ref
    ph_gap = sh.add(f"Gap to {th.label}", fmt_delta(gap, m.unit), gap)
    ok = gap >= 0 if th.higher_is_better else gap <= 0
    word = ("above" if gap >= 0 else "below")
    sh.signals.append(f"{m.label} is {word} the {th.label} of {ph_ref} ({ph_gap}) - "
                      f"{'meets' if ok else 'misses'} the benchmark.")
    sh.sentences.append(f"This is {word} the {th.label} of {ph_ref}.")


# -- one dimension --------------------------------------------------------------
def _breakdown(sh: FactSheet, rs: ResultSet, m: sem.Measure, store) -> None:
    q, df = rs.query, rs.df
    d = q.group_dims[0]
    dl = sem.DIMENSIONS[d].label.lower()
    s = df[[d, m.id]].dropna()
    if s.empty:
        sh.sentences.append(f"No {_lc(m.label)} figures are available by {dl}.")
        return
    s = s.sort_values(m.id, ascending=False, kind="stable")
    total = rs.totals.get(m.id)
    n = len(df)
    ph_n = sh.add(f"Number of {dl} values shown", str(n), n)
    if _valid(total):
        ph_t = sh.add(f"{m.label} overall", fmt_value(total, m.unit), total)
        if q.limit:      # top/bottom N: the total covers every group, not just the ones listed
            sh.sentences.append(f"Across all {dl} values, overall {_lc(m.label)} is {ph_t}.")
        else:
            sh.sentences.append(f"Overall {_lc(m.label)} is {ph_t} across {ph_n} {dl} values.")
    top, bot = s.iloc[0], s.iloc[-1]
    ph_top = sh.add(f"Highest {dl}: {top[d]} - {m.label}", fmt_value(top[m.id], m.unit), top[m.id])
    sh.sentences.append(f"{top[d]} is highest at {ph_top}.")
    if len(s) > 1:
        scope = f"Lowest of the {n} shown" if q.limit else "Lowest"
        ph_bot = sh.add(f"{scope} {dl}: {bot[d]} - {m.label}", fmt_value(bot[m.id], m.unit), bot[m.id])
        sh.sentences.append(f"{bot[d]} is the lowest{' of those shown' if q.limit else ''} at {ph_bot}.")
    if len(s) > 2:
        sec = s.iloc[1]
        sh.add(f"Second highest {dl}: {sec[d]} - {m.label}", fmt_value(sec[m.id], m.unit), sec[m.id])
    if is_additive(m) and _valid(total) and total:
        share = top[m.id] / total * 100
        ph_sh = sh.add(f"{top[d]} share of total {_lc(m.label)}", fmt_value(share, "percent"), share)
        sh.signals.append(f"{top[d]} accounts for {ph_sh} of the total.")
        if len(s) >= 3 and not rs.query.limit:
            top3 = s.head(3)[m.id].sum() / total * 100
            ph3 = sh.add(f"Top three {dl} values share of total", fmt_value(top3, "percent"), top3)
            sh.signals.append(f"The top three {dl} values together account for {ph3}.")
    if f"{m.id}__delta" in df:
        dd = df[[d, f"{m.id}__delta"]].dropna()
        if len(dd):
            up, dn = dd.loc[dd[f"{m.id}__delta"].idxmax()], dd.loc[dd[f"{m.id}__delta"].idxmin()]
            uv, dv = up[f"{m.id}__delta"], dn[f"{m.id}__delta"]
            ph_up = sh.add(f"Change vs previous period, {_move(uv, True)}: {up[d]}", fmt_delta(uv, m.unit), uv)
            ph_dn = sh.add(f"Change vs previous period, {_move(dv, False)}: {dn[d]}", fmt_delta(dv, m.unit), dv)
            sh.sentences.append(f"Versus the previous period, the strongest movement was {up[d]} ({ph_up}) and the weakest was {dn[d]} ({ph_dn}).")


# -- trend ---------------------------------------------------------------------------
def _trend(sh: FactSheet, rs: ResultSet, m: sem.Measure) -> None:
    df = rs.df
    s = df[["_period", m.id]].dropna()
    if s.empty:
        sh.sentences.append(f"No {_lc(m.label)} figures are available over time.")
        return
    first, last = s.iloc[0], s.iloc[-1]
    ph_f = sh.add(f"{m.label} in {first['_period']}", fmt_value(first[m.id], m.unit), first[m.id])
    ph_l = sh.add(f"{m.label} in {last['_period']}", fmt_value(last[m.id], m.unit), last[m.id])
    sh.sentences.append(f"{m.label} was {ph_f} in {first['_period']} and {ph_l} in {last['_period']}.")
    if len(s) > 1:
        chg = last[m.id] - first[m.id]
        ph_c = sh.add(f"Change from {first['_period']} to {last['_period']}", fmt_delta(chg, m.unit), chg)
        word = "up" if chg > 0 else ("down" if chg < 0 else "unchanged")
        if m.unit not in ("percent", "days") and first[m.id]:
            pc = chg / abs(first[m.id]) * 100
            ph_pc = sh.add(f"% change from {first['_period']} to {last['_period']}",
                           fmt_delta(pc, "percent").replace(" pp", "%"), pc)
            sh.signals.append(f"Over the window {_lc(m.label)} is {word} ({ph_c}, {ph_pc}).")
        else:
            sh.signals.append(f"Over the window {_lc(m.label)} is {word} ({ph_c}).")
        pk, tr = s.loc[s[m.id].idxmax()], s.loc[s[m.id].idxmin()]
        ph_pk = sh.add(f"Peak: {pk['_period']} - {m.label}", fmt_value(pk[m.id], m.unit), pk[m.id])
        ph_tr = sh.add(f"Low: {tr['_period']} - {m.label}", fmt_value(tr[m.id], m.unit), tr[m.id])
        sh.sentences.append(f"The peak was {pk['_period']} at {ph_pk} and the low was {tr['_period']} at {ph_tr}.")
        if len(s) > 2:
            ph_a = sh.add(f"Average {_lc(m.label)} per period"
                          + ("" if is_additive(m) else " (simple mean of the period values)"),
                          fmt_value(s[m.id].mean(), m.unit), float(s[m.id].mean()))
            sh.sentences.append(f"The average per period is {ph_a}.")
            diffs = s[m.id].diff().dropna()
            if len(diffs):
                i_up, i_dn = diffs.idxmax(), diffs.idxmin()
                wu, wd = _move(diffs[i_up], True), _move(diffs[i_dn], False)
                ph_u = sh.add(f"Period-on-period {wu}: into {s.loc[i_up, '_period']}", fmt_delta(diffs[i_up], m.unit), diffs[i_up])
                ph_d = sh.add(f"Period-on-period {wd}: into {s.loc[i_dn, '_period']}", fmt_delta(diffs[i_dn], m.unit), diffs[i_dn])
                sh.signals.append(f"Period-on-period, the {wu} was into {s.loc[i_up, '_period']} ({ph_u}); "
                                  f"the {wd} was into {s.loc[i_dn, '_period']} ({ph_d}).")


# -- one dimension over time / two dimensions ----------------------------------------------
def _breakdown_over_time(sh: FactSheet, rs: ResultSet, m: sem.Measure) -> None:
    q, df = rs.query, rs.df
    d = q.group_dims[0]
    dl = sem.DIMENSIONS[d].label.lower()
    total = rs.totals.get(m.id)
    if _valid(total):
        ph_t = sh.add(f"{m.label} overall", fmt_value(total, m.unit), total)
        sh.sentences.append(f"Overall {_lc(m.label)} across the window is {ph_t}.")
    periods = list(dict.fromkeys(df["_period"]))
    last_p = periods[-1]
    lastdf = df[df["_period"] == last_p][[d, m.id]].dropna()
    if len(lastdf):
        t = lastdf.loc[lastdf[m.id].idxmax()]
        ph = sh.add(f"Leading {dl} in {last_p}: {t[d]} - {m.label}", fmt_value(t[m.id], m.unit), t[m.id])
        sh.sentences.append(f"In {last_p}, {t[d]} leads at {ph}.")
    if len(periods) > 1:
        first_p = periods[0]
        a = df[df["_period"] == first_p].set_index(d)[m.id]
        b = df[df["_period"] == last_p].set_index(d)[m.id]
        ch = (b - a).dropna()
        if len(ch):
            up, dn = ch.idxmax(), ch.idxmin()
            ph_u = sh.add(f"Change {first_p} to {last_p}, {_move(ch[up], True)}: {up}", fmt_delta(ch[up], m.unit), ch[up])
            ph_d = sh.add(f"Change {first_p} to {last_p}, {_move(ch[dn], False)}: {dn}", fmt_delta(ch[dn], m.unit), ch[dn])
            sh.sentences.append(f"From {first_p} to {last_p}, the strongest movement was {up} ({ph_u}) and the weakest was {dn} ({ph_d}).")
    _over_time_extras(sh, rs, m, d, dl, periods)


def _over_time_extras(sh: FactSheet, rs: ResultSet, m: sem.Measure, d: str, dl: str, periods: list) -> None:
    """The month-by-month story behind a breakdown chart: the combined trend and who drives it."""
    df = rs.df
    n_g = int(df[d].nunique())
    sh.add(f"Number of {dl} values", str(n_g), n_g)
    sh.add("Number of periods shown", str(len(periods)), len(periods))
    if is_additive(m):
        per = df.groupby("_period", sort=False)[m.id].sum(min_count=1).dropna()
        if len(per) > 1:
            fp, lp = per.index[0], per.index[-1]
            ph_f = sh.add(f"All {dl} values combined, {fp} - {m.label}", fmt_value(per.iloc[0], m.unit), per.iloc[0])
            ph_l = sh.add(f"All {dl} values combined, {lp} - {m.label}", fmt_value(per.iloc[-1], m.unit), per.iloc[-1])
            sh.sentences.append(f"Combined across {dl} values, {_lc(m.label)} was {ph_f} in {fp} and {ph_l} in {lp}.")
            pk, lo = per.idxmax(), per.idxmin()
            ph_pk = sh.add(f"Peak period for all {dl} values combined: {pk} - {m.label}", fmt_value(per[pk], m.unit), per[pk])
            ph_lo = sh.add(f"Lowest period for all {dl} values combined: {lo} - {m.label}", fmt_value(per[lo], m.unit), per[lo])
            sh.signals.append(f"Combined, the peak was {pk} ({ph_pk}) and the lowest was {lo} ({ph_lo}).")
            if per.iloc[0]:
                pc = (per.iloc[-1] - per.iloc[0]) / abs(per.iloc[0]) * 100
                ph_pc = sh.add(f"% change in the combined total, {fp} to {lp}",
                               fmt_delta(pc, "percent").replace(" pp", "%"), pc)
                sh.signals.append(f"The combined total moved {ph_pc} from {fp} to {lp}.")
        if not sem.is_point_in_time(m):
            by_g = df.groupby(d)[m.id].sum(min_count=1).dropna()
            if len(by_g) > 1 and by_g.sum():
                top = by_g.idxmax()
                ph_t = sh.add(f"Highest {dl} across the whole window: {top} - {m.label}", fmt_value(by_g[top], m.unit), by_g[top])
                ph_s = sh.add(f"{top} share of the window total", fmt_value(by_g[top] / by_g.sum() * 100, "percent"),
                              by_g[top] / by_g.sum() * 100)
                sh.sentences.append(f"Across the whole window {top} is highest at {ph_t}.")
                sh.signals.append(f"{top} accounts for {ph_s} of the window total.")
    else:
        last_p = periods[-1]
        ld = df[df["_period"] == last_p][[d, m.id]].dropna()
        if len(ld) > 1:
            lo = ld.loc[ld[m.id].idxmin()]
            ph = sh.add(f"Lowest {dl} in {last_p}: {lo[d]} - {m.label}", fmt_value(lo[m.id], m.unit), lo[m.id])
            sh.sentences.append(f"In {last_p}, {lo[d]} is lowest at {ph}.")


def _two_dims(sh: FactSheet, rs: ResultSet, m: sem.Measure) -> None:
    q, df = rs.query, rs.df
    d0, d1 = q.group_dims
    s = df[[d0, d1, m.id]].dropna()
    if s.empty:
        return
    total = rs.totals.get(m.id)
    if _valid(total):
        ph_t = sh.add(f"{m.label} overall", fmt_value(total, m.unit), total)
        sh.sentences.append(f"Overall {_lc(m.label)} is {ph_t}.")
    t = s.loc[s[m.id].idxmax()]
    ph = sh.add(f"Largest combination: {t[d0]} / {t[d1]} - {m.label}", fmt_value(t[m.id], m.unit), t[m.id])
    sh.sentences.append(f"The largest combination is {t[d0]} / {t[d1]} at {ph}.")


# -- benchmark signals ------------------------------------------------------------------------
def _threshold_signals(sh: FactSheet, rs: ResultSet, m: sem.Measure, store) -> None:
    th = m.threshold
    if th is None or m.id not in rs.df:
        return
    ref = sem.resolve_ref(th.value, store) if isinstance(th.value, sem.Ref) else th.value
    q, df = rs.query, rs.df
    if q.group_dims and q.grain == "none":
        vals = df[m.id].dropna()
        if len(vals):
            meets = int((vals >= ref).sum() if th.higher_is_better else (vals <= ref).sum())
            miss = len(vals) - meets
            ph_ref = sh.add(th.label.capitalize(), fmt_value(ref, m.unit), ref)
            ph_m = sh.add(f"Groups meeting the {th.label}", str(meets), meets)
            ph_x = sh.add(f"Groups missing the {th.label}", str(miss), miss)
            side_ok, side_bad = (("at or above", "below") if th.higher_is_better else ("at or below", "above"))
            sh.signals.append(f"Against the {th.label} of {ph_ref}: {ph_m} group(s) are {side_ok} it and {ph_x} are {side_bad} it.")
    elif q.grain != "none" and not q.group_dims:
        vals = df[m.id].dropna()
        if len(vals):
            miss = int((vals < ref).sum() if th.higher_is_better else (vals > ref).sum())
            ph_ref = sh.add(th.label.capitalize(), fmt_value(ref, m.unit), ref)
            ph_x = sh.add(f"Periods missing the {th.label}", str(miss), miss)
            ph_n = sh.add("Periods shown", str(len(vals)), len(vals))
            sh.signals.append(f"Against the {th.label} of {ph_ref}: {ph_x} of {ph_n} periods miss it.")
