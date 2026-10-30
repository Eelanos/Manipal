"""
Validation + entity resolution: turns a model-written QuerySpec into a
ResolvedQuery the engine can execute, or raises PlanError with a message
precise enough to show the user or send back to the planner.

Entity resolution policy (accuracy over cleverness):
  1. exact match on a label/alias (case & punctuation insensitive)  -> use it
  2. every word the user typed appears in a value ("gloves")        -> all of those
  3. a value appears inside what the user typed ("cardiology dept") -> the longest
  4. a close spelling (difflib >= cutoff, unambiguous)              -> use it, say so
  5. otherwise                                                      -> PlanError with suggestions
It never silently picks a weak match.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional

from app.chat import semantic as sem
from app.chat.catalog import Catalog, DimInfo, normalize_text
from app.chat.settings import ChatSettings
from app.chat.spec import QuerySpec
from app.chat.timeparse import (Period, PlanError, expand_to_whole_months,
                                resolve_period)


@dataclass
class ResolvedFilter:
    dim_id: str
    op: str                      # in | not_in
    raw_values: list             # real data values (may include None / bools)
    labels: list                 # display labels of the same values
    typed: list                  # what the user typed


@dataclass
class ResolvedQuery:
    spec: QuerySpec
    title: str
    measures: list               # list[sem.Measure]
    group_dims: list             # list[str] dimension ids
    grain: str                   # none|month|quarter|fiscal_year|year
    period: Period
    filters: list                # list[ResolvedFilter]
    tables: set
    sort_by: str                 # measure id
    sort_desc: bool
    limit: Optional[int]
    show_share: bool
    compare_previous: bool
    chart: str
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Value matching
# ---------------------------------------------------------------------------
def _suggest(info: DimInfo, typed: str, n: int = 5) -> list[str]:
    keys = list(info.alias_to_raw)
    close = difflib.get_close_matches(normalize_text(typed), keys, n=n * 2, cutoff=0.5)
    out: list[str] = []
    for k in close:
        for raw in info.alias_to_raw[k]:
            lab = info.raw_to_label[raw]
            if lab not in out:
                out.append(lab)
    if not out:                       # nothing close: show a few real values
        out = info.ordered_labels[:n]
    return out[:n]


def match_value(info: DimInfo, typed: str, cutoff: float):
    """
    Returns (raw_values, note|None) or None when nothing matches acceptably.
    """
    n = normalize_text(typed)
    if not n:
        return None
    a2r = info.alias_to_raw

    if n in a2r:                                                  # 1. exact
        return sorted(a2r[n], key=str), None

    tokens = set(n.split())
    sup = {a for a in a2r if tokens <= set(a.split())}            # 2. all typed words present
    if sup:
        raws = set().union(*(a2r[a] for a in sup))
        if len(raws) <= 25:
            labs = sorted(info.raw_to_label[r] for r in raws)
            note = (f"'{typed}' matched {len(raws)} {info.dim.label.lower()} values: "
                    + ", ".join(labs[:6]) + ("…" if len(labs) > 6 else ""))
            return sorted(raws, key=str), (note if len(raws) > 1 else None)

    inside = [a for a in a2r if set(a.split()) <= tokens]         # 3. value inside typed text
    if inside:
        best = max(len(a.split()) for a in inside)
        raws = set().union(*(a2r[a] for a in inside if len(a.split()) == best))
        if len(raws) == 1:
            return list(raws), None

    close = difflib.get_close_matches(n, list(a2r), n=2, cutoff=cutoff)   # 4. close spelling
    if close:
        if len(close) == 2:
            r1 = difflib.SequenceMatcher(None, n, close[0]).ratio()
            r2 = difflib.SequenceMatcher(None, n, close[1]).ratio()
            if r1 - r2 < 0.05 and a2r[close[0]] != a2r[close[1]]:
                return None                                       # too close to call
        raws = a2r[close[0]]
        lab = info.raw_to_label[sorted(raws, key=str)[0]]
        return sorted(raws, key=str), f"Read '{typed}' as '{lab}'."
    return None


# ---------------------------------------------------------------------------
# Query validation
# ---------------------------------------------------------------------------
def _dim_tables_msg(dim: sem.Dimension, tables: set[str]) -> str:
    lacking = sorted(t for t in tables if t not in dim.columns)
    names = ", ".join(sem.TABLES[t].label.lower() for t in lacking)
    return (f"'{dim.label}' is not available for {names} data. "
            f"{sem.TABLES[lacking[0]].description}")


def resolve_query(spec: QuerySpec, cat: Catalog, settings: ChatSettings) -> ResolvedQuery:
    notes: list[str] = []

    # --- measures ---------------------------------------------------------
    if not spec.measures:
        raise PlanError("A query needs at least one measure.")
    measure_ids = list(dict.fromkeys(spec.measures))
    if len(measure_ids) > settings.max_measures:
        raise PlanError(f"At most {settings.max_measures} measures per query; "
                        f"split the question into separate queries.")
    measures = [sem.MEASURES[m] for m in measure_ids]
    tables = set().union(*(sem.measure_tables(m) for m in measures))

    # --- grouping ---------------------------------------------------------
    group_dims = list(dict.fromkeys(spec.group_by))
    if len(group_dims) > 2:
        raise PlanError("At most 2 group-by dimensions per query.")
    for d in group_dims:
        dim = sem.DIMENSIONS[d]
        if not sem.dimension_supported_on(dim, tables):
            raise PlanError(_dim_tables_msg(dim, tables))
    grain = spec.time_grain
    if grain != "none" and len(group_dims) == 2:
        raise PlanError("A trend over time can be broken down by at most 1 dimension.")

    # --- period -----------------------------------------------------------
    period = resolve_period(spec.time, cat)
    if any(sem.TABLES[t].kind == "monthly" for t in tables):
        period = expand_to_whole_months(period)
    notes.extend(period.notes)

    # --- filters ----------------------------------------------------------
    filters: list[ResolvedFilter] = []
    for f in spec.filters[:8]:
        dim_id = f.dimension
        dim = sem.DIMENSIONS[dim_id]
        if not f.values:
            continue
        if not sem.dimension_supported_on(dim, tables):
            raise PlanError(_dim_tables_msg(dim, tables))
        raws: list = []
        for typed in f.values:
            hit = match_value(cat.dim(dim_id), typed, settings.fuzzy_cutoff)
            used_dim = dim_id
            if hit is None:
                # The model may have filed a real value under the wrong
                # dimension ("Pune" under department). Re-home it only when
                # the match is EXACT and in exactly one other usable dimension.
                n = normalize_text(typed)
                homes = [d2 for d2, i2 in cat.dims.items()
                         if d2 != dim_id and n in i2.alias_to_raw
                         and sem.dimension_supported_on(i2.dim, tables)]
                if len(homes) == 1:
                    used_dim = homes[0]
                    hit = match_value(cat.dim(used_dim), typed, settings.fuzzy_cutoff)
                    notes.append(f"Read '{typed}' as a {sem.DIMENSIONS[used_dim].label.lower()}.")
            if hit is None:
                sugg = _suggest(cat.dim(dim_id), typed)
                raise PlanError(
                    f"I couldn't find a {dim.label.lower()} matching '{typed}'.", sugg)
            vals, note = hit
            if note:
                notes.append(note)
            if used_dim != dim_id:
                # flush what we have for the original dim, start a new filter for the re-homed dim
                info2 = cat.dim(used_dim)
                filters.append(ResolvedFilter(used_dim, f.op, vals,
                                              [info2.raw_to_label[v] for v in vals], [typed]))
            else:
                raws.extend(vals)
        if raws:
            info = cat.dim(dim_id)
            uniq = list(dict.fromkeys(raws))
            filters.append(ResolvedFilter(dim_id, f.op, uniq,
                                          [info.raw_to_label[v] for v in uniq], list(f.values)))

    # --- ranking / limit ----------------------------------------------------
    sort_by = spec.sort_by if spec.sort_by in measure_ids else measure_ids[0]
    limit = spec.limit
    if limit is not None:
        if limit < 1:
            limit = None
        else:
            limit = min(limit, settings.max_limit)
    if limit is not None and not group_dims:
        notes.append("'Top N' ignored: there is no breakdown to rank.")
        limit = None

    show_share = spec.show_share
    if show_share and not group_dims:
        show_share = False
    if show_share and not any(is_additive(m) for m in measures):
        notes.append("Share of total skipped: these measures cannot be summed across groups.")
        show_share = False

    compare = spec.compare_previous
    if compare and spec.time.kind == "all":
        notes.append("No comparison period: the whole dataset was selected.")
        compare = False

    return ResolvedQuery(
        spec=spec, title=spec.title.strip() or ", ".join(m.label for m in measures),
        measures=measures, group_dims=group_dims, grain=grain, period=period,
        filters=filters, tables=tables, sort_by=sort_by, sort_desc=spec.sort_desc,
        limit=limit, show_share=show_share, compare_previous=compare,
        chart=spec.chart, notes=notes,
    )


def is_additive(m: sem.Measure) -> bool:
    """True when summing the measure across groups gives the overall figure."""
    def add(e) -> bool:
        if isinstance(e, sem.Agg):
            return e.op in ("sum", "count")
        if isinstance(e, sem.BinOp):
            return e.op == "sub" and e.scale == 1.0 and add(e.left) and add(e.right)
        return False
    return add(m.expr)
