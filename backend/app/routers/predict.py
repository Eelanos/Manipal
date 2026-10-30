"""
Predictive Analysis endpoints (rule-based demand & replenishment planning).

Own router and own response shape, like RCA. The global filter bar still
applies through the shared get_filters dependency: Unit / Region / Zone /
Cluster / Stock Take Group narrow everything; Department narrows only the
DEMAND views (stock is not tracked by department); the Period filter is not
used because planning always looks forward from the latest stock snapshot.

Every setting's default and limits come from app.predict.params.SETTINGS - the
same spec is published by /options so the frontend hardcodes nothing.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.data_loader import DataStore, get_store
from app.filters import Filters, get_filters
from app.predict import engine
from app.predict import params as P
from app.predict.engine import PredictError

router = APIRouter(prefix="/api/predict", tags=["predict"])

_S = P.SETTINGS


def get_params(
    window_months: int = Query(_S["window_months"].default),
    lead_days: int = Query(_S["lead_days"].default),
    buffer_days: int = Query(_S["buffer_days"].default),
    plan_days: int = Query(_S["plan_days"].default),
    max_cover_days: int = Query(_S["max_cover_days"].default),
    expiry_horizon_days: int = Query(_S["expiry_horizon_days"].default),
    seasonality: bool = Query(_S["seasonality"].default),
) -> P.Params:
    """Validate against the same limits /options advertises; bad input -> HTTP 400."""
    try:
        return P.make_params(
            window_months=window_months, lead_days=lead_days, buffer_days=buffer_days,
            plan_days=plan_days, max_cover_days=max_cover_days,
            expiry_horizon_days=expiry_horizon_days, seasonality=seasonality)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _run(fn, *args):
    try:
        return fn(*args)
    except PredictError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/options")
def predict_options(store: DataStore = Depends(get_store)) -> dict:
    """Everything the page's controls need - settings spec, defaults, statuses, scope."""
    snap = engine._snapshot(store)
    return {
        "as_of": snap.strftime("%Y-%m-%d"),
        "settings": [
            {"key": s.key, "label": s.label, "default": s.default, "min": s.minimum, "max": s.maximum,
             "step": s.step, "unit": s.unit, "help": s.help, "choices": list(s.choices) if s.choices else None,
             "kind": "toggle" if isinstance(s.default, bool) else ("choice" if s.choices else "number")}
            for s in _S.values()
        ],
        "statuses": [{"key": k, "help": P.STATUS_HELP[k]} for k in P.STATUSES],
        "forecast_months": P.FORECAST_MONTHS,
        "history_months": P.HISTORY_MONTHS,
        "horizon_days": P.HORIZON_DAYS,
        "units": store.unit_options,
    }


@router.get("/overview")
def predict_overview(f: Filters = Depends(get_filters), p: P.Params = Depends(get_params),
                     store: DataStore = Depends(get_store)) -> dict:
    return _run(engine.build_overview, store, f, p)


@router.get("/status")
def predict_status(status: str = Query(...),
                   f: Filters = Depends(get_filters), p: P.Params = Depends(get_params),
                   store: DataStore = Depends(get_store)) -> dict:
    """Every item x unit line behind one slice of the stock-health donut."""
    return _run(engine.build_status, store, f, p, status)


@router.get("/item")
def predict_item(item_id: str = Query(...), unit_id: str = Query(...),
                 f: Filters = Depends(get_filters), p: P.Params = Depends(get_params),
                 store: DataStore = Depends(get_store)) -> dict:
    return _run(engine.build_item, store, f, p, item_id, unit_id)
