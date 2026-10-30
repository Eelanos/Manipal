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
    }


@router.get("/analysis")
def rca_analysis(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    path: list[str] = Query(default=[], description="Drill steps, e.g. unit:PUN (repeat the parameter)"),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    return _wrap(engine.analyze, store, f, metric, month, compare, path)


@router.get("/tree")
def rca_tree(
    metric: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    compare: str = Query("prior_month"),
    f: Filters = Depends(get_filters),
    store: DataStore = Depends(get_store),
) -> dict:
    return _wrap(tree.walk, store, f, metric, month, compare)
