"""
Predictive Analysis: every adjustable setting and every constant, in ONE place.

Nothing in engine.py or the router contains a number that is a business
assumption - they all come from here. The frontend does not hardcode any of
them either: it reads GET /api/predict/options.

Defaults can be overridden per deployment with environment variables
(PREDICT_DEFAULT_<KEY>, e.g. PREDICT_DEFAULT_LEAD_DAYS=10), so changing an
assumption never needs a code edit.

IMPORTANT: lead time and buffer are ASSUMPTIONS. The dataset has no vendor lead
times and no purchase-order receipt dates, so these are settings the user can
change on the page, not facts read from the data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default, cast):
    raw = os.environ.get(f"PREDICT_DEFAULT_{key.upper()}")
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


def _bool(raw: str) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    default: int | bool
    minimum: int | None
    maximum: int | None
    step: int | None
    unit: str
    help: str
    choices: tuple[int, ...] | None = None   # a closed list instead of a range


SETTINGS: dict[str, Setting] = {s.key: s for s in [
    Setting("window_months", "Usage based on last", _env("window_months", 6, int), None, None, None,
            "months", "How many recent months are averaged to get the daily usage of each item.",
            choices=(3, 6, 12)),
    Setting("lead_days", "Delivery time", _env("lead_days", 7, int), 1, 90, 1,
            "days", "Assumed days between placing an order and receiving it. Not in the data - change it to see what-if."),
    Setting("buffer_days", "Safety buffer", _env("buffer_days", 5, int), 0, 60, 1,
            "days", "Extra days of usage kept as a cushion against late deliveries or a busy spell."),
    Setting("plan_days", "Plan for next", _env("plan_days", 30, int), 7, 120, 1,
            "days", "How many days of usage an order should cover once it arrives."),
    Setting("max_cover_days", "Excess above", _env("max_cover_days", 90, int), 30, 365, 5,
            "days of cover", "Stock beyond this many days of usage is counted as excess."),
    Setting("expiry_horizon_days", "Expiry look-ahead", _env("expiry_horizon_days", 180, int), 30, 365, 5,
            "days", "Batches expiring within this many days are checked for being used up in time."),
    Setting("seasonality", "Adjust for seasonality", _env("seasonality", True, _bool), None, None, None,
            "", "Scale usage by the month-of-year pattern seen in past data (needs one full year of history)."),
]}


@dataclass(frozen=True)
class Params:
    window_months: int
    lead_days: int
    buffer_days: int
    plan_days: int
    max_cover_days: int
    expiry_horizon_days: int
    seasonality: bool

    def key(self) -> tuple:
        return (self.window_months, self.lead_days, self.buffer_days, self.plan_days,
                self.max_cover_days, self.expiry_horizon_days, self.seasonality)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in SETTINGS}


def make_params(**kw) -> Params:
    """Validate against SETTINGS (the same limits the API advertises). Raises ValueError."""
    out = {}
    for key, s in SETTINGS.items():
        v = kw.get(key, s.default)
        if isinstance(s.default, bool):
            out[key] = bool(v)
            continue
        v = int(v)
        if s.choices is not None and v not in s.choices:
            raise ValueError(f"{s.label} must be one of {list(s.choices)}.")
        if s.choices is None and not (s.minimum <= v <= s.maximum):
            raise ValueError(f"{s.label} must be between {s.minimum} and {s.maximum}.")
        out[key] = v
    return Params(**out)


def default_params() -> Params:
    return make_params()


# --- Fixed constants (not user settings) ------------------------------------
HISTORY_MONTHS = 12          # months of actuals drawn on the demand chart
FORECAST_MONTHS = 3          # months of forecast drawn after the actuals
HORIZON_DAYS = 730           # how far ahead run-out is searched; beyond this is "730+"
TOP_COVER_ROWS = 12          # bars on the "lowest days of cover" chart
MAX_TABLE_ROWS = 500         # rows returned per table (a flag says when more exist)
PROJECTION_MIN_DAYS = 60     # item stock projection: shortest span
PROJECTION_MAX_DAYS = 180    # item stock projection: longest span
BACKTEST_MIN_SAMPLES = 6     # fewest past forecasts needed before a range / accuracy is shown
BAND_LOW_Q = 0.10            # forecast range = 10th..90th percentile of how past forecasts missed
BAND_HIGH_Q = 0.90
OPEN_PO_STATUS = "In-Transit"   # purchase orders with this status count as "on order"

# --- Stock status classes (order = precedence AND display order) -------------
STATUS_CRITICAL = "Critical"
STATUS_ORDER_SOON = "Order soon"
STATUS_HEALTHY = "Healthy"
STATUS_EXCESS = "Excess"
STATUS_NO_USAGE = "No recent usage"
STATUS_NO_RECORD = "No stock record"
STATUSES = [STATUS_CRITICAL, STATUS_ORDER_SOON, STATUS_HEALTHY, STATUS_EXCESS, STATUS_NO_USAGE, STATUS_NO_RECORD]
STATUS_HELP = {
    STATUS_CRITICAL: "Usable stock will run out before a new order could arrive, and stock + on order is still below the reorder point.",
    STATUS_ORDER_SOON: "Stock + on order is below the reorder point, but usable stock will not run out before delivery.",
    STATUS_HEALTHY: "Stock + on order covers the delivery time and safety buffer, and is not excessive.",
    STATUS_EXCESS: "More usable stock than the maximum days of cover allows.",
    STATUS_NO_USAGE: "Stock on hand but no usage in the chosen window.",
    STATUS_NO_RECORD: "Used recently, but there is no stock record on the snapshot date - most likely a data gap, so it is not planned.",
}
