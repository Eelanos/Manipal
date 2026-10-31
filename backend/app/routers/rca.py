"""
Root cause analysis endpoints. Separate from the five dashboard routers and
from the response envelope on purpose: an RCA answer is not a set of KPI cards
and charts, and forcing it into DashboardResponse would bend both.

The Unit / Stock Take Group / Department filters from the top bar apply (they
arrive through the same get_filters dependency as every dashboard). The Period
filter does not: RCA explains ONE month against a comparison, chosen on the page.
"""

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import (RCA_HOME_CARDS, RCA_MATERIAL_SHARE_PCT, RCA_MIN_HISTORY_MONTHS,
                        RCA_MIN_OVERINDEX_PP, RCA_Z_UNUSUAL, RCA_Z_WATCH)
from app.data_loader import DataStore, get_store
from app.filters import Filters, get_filters
from app.rca import engine, tree
from app.rca.dims import DIMS
from app.rca.measures import COMPARE_LABELS, MEASURES, RcaError

router = APIRouter(prefix="/api/rca", tags=["rca"])


def _wrap(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except RcaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/options")
def rca_options(store: DataStore = Depends(get_store)) -> dict:
    """Everything the RCA page's controls need, so the frontend hardcodes nothing."""
    months = engine.months_available(store)
    metrics = []
    for m in MEASURES.values():
        metrics.append({
            "key": m.key, "label": m.label, "fmt": m.fmt, "unit_word": m.unit_word,
            "higher_is": m.higher_is, "definition": m.definition,
            "compares": [{"key": c, "label": (f"Target ({m.target:.0f}%)" if c == "target" else COMPARE_LABELS[c])}
                         for c in m.compares],
            "dims": [{"key": d, "label": DIMS[d].label} for d in m.dims],
            "has_tree": m.key in tree.TREE_METRICS,
            "tree_compares": [c for c in m.compares if c in tree.TREE_COMPARES] if m.key in tree.TREE_METRICS else [],
        })
    return {
        "metrics": metrics,
        "months": [{"value": d.strftime("%Y-%m"), "label": d.strftime("%b %Y"),
                    "has_prior_month": (d - pd.DateOffset(months=1)) in months,
                    "has_same_month_last_year": (d - pd.DateOffset(months=12)) in months}
                   for d in months],
        "default_month": months[-1].strftime("%Y-%m"),
        "home_cards": RCA_HOME_CARDS,
        # The rules behind every status badge, so the screen can state them instead of hard-coding them.
        "thresholds": {"z_unusual": RCA_Z_UNUSUAL, "z_watch": RCA_Z_WATCH,
                       "material_share_pct": RCA_MATERIAL_SHARE_PCT, "min_overindex_pp": RCA_MIN_OVERINDEX_PP,
                       "min_history_months": RCA_MIN_HISTORY_MONTHS},
    }


@router.get("/analysis")
def rca_analysis(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    path: list[str] = Query(default=[], description="Drill steps, e.g. unit:PUN (repeat the parameter)"),
    full: bool = Query(False, description="List every segment, not just the biggest few"),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    return _wrap(engine.analyze, store, f, metric, month, compare, path, full)


@router.get("/lens")
def rca_lens(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    dim: str = Query(..., description="The view: unit, region, doctor, department..."),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    """Every entity of one kind (all units, all doctors...) with its part of the change, status and top driver."""
    return _wrap(engine.lens, store, f, metric, month, compare, dim)


@router.get("/cause")
def rca_cause(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    dim: str = Query(...),
    segment: str = Query(...),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    """The strongest driver inside one entity. Separate from /lens so the cards appear before it is known."""
    return _wrap(engine.cause, store, f, metric, month, compare, dim, segment)


@router.get("/entity")
def rca_entity(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    dim: str = Query(...),
    segment: str = Query(...),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    """One entity: how it moved, whether that is unusual for it, and the ranked drivers inside it."""
    return _wrap(engine.entity, store, f, metric, month, compare, dim, segment)


@router.get("/tree")
def rca_tree(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    path: list[str] = Query(default=[], description="Optional: build the tree for one segment, e.g. unit:PUN"),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    return _wrap(tree.walk, store, f, metric, month, compare, path)
