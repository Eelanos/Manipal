"""
FastAPI entrypoint. Loads the workbook once at startup, mounts one router per
dashboard, and exposes the filter option lists the frontend FilterBar needs.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (ALLOWED_ORIGINS, AS_OF_DATE, DATA_END, DATA_START,
                        STOCK_TAKE_GROUPS, TIER_LABELS)
from app.data_loader import get_store
from app.filters import PRESETS
from app.routers import (consumption, formulary, inventory, rca,
                         sob_compliance, sob_opportunities)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the cache at startup so the first request isn't a slow Excel read.
    store = get_store()
    print(f"Loaded {len(store.consumption):,} consumption rows, "
          f"{len(store.purchase):,} purchase rows, "
          f"{len(store.inventory):,} inventory rows.")
    yield


app = FastAPI(title="Manipal Analytics Dashboard API", version="0.1.0",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(consumption.router)
app.include_router(inventory.router)
app.include_router(formulary.router)
app.include_router(sob_opportunities.router)
app.include_router(sob_compliance.router)
app.include_router(rca.router)

# "Ask Manipal" conversational layer. Additive and isolated: if it cannot load
# (e.g. the openai package is not installed yet) the dashboards run unchanged.
try:
    from app.chat.router import router as chat_router
    app.include_router(chat_router)
except Exception as exc:  # pragma: no cover
    print(f"[chat] Ask Manipal disabled: {exc}")


@app.get("/api/health")
def health():
    store = get_store()
    return {
        "status": "ok",
        "as_of_date": AS_OF_DATE.isoformat(),
        "rows": {
            "consumption": len(store.consumption),
            "purchase": len(store.purchase),
            "inventory": len(store.inventory),
        },
    }


@app.get("/api/filter-options")
def filter_options():
    """
    Feeds the FilterBar dropdowns so the frontend hardcodes nothing.
    `units` carries each unit's Cluster/Zone/Region so the frontend can
    cascade the dropdowns without another round trip.
    """
    store = get_store()
    return {
        "regions": store.regions,
        "zones": store.zones,
        "clusters": store.clusters,
        "units": store.unit_options,
        "departments": store.departments,
        "stock_take_groups": STOCK_TAKE_GROUPS,
        "presets": list(PRESETS.keys()),
        "tier_labels": TIER_LABELS,
        "date_min": DATA_START.isoformat(),
        "date_max": DATA_END.isoformat(),
    }
