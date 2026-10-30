"""
Central configuration. Every constant the dashboards depend on lives HERE and
nowhere else, so changing one is a one-line edit rather than a hunt.
"""

from datetime import date
from pathlib import Path

# --- Paths ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# The app reads Parquet, not Excel. The v2 workbook is 21 MB and takes ~50s
# for pandas to parse - unacceptable as a startup cost, and --reload would pay
# it on every save. Parquet loads the same data in 0.4s.
# Regenerate both with: python extend_data.py
PARQUET_DIR = DATA_DIR / "parquet"
FLAGS_PATH = DATA_DIR / "synthetic_flags.json"

# --- The single most important constant in this app -----------------------
# The dataset runs to 31 Dec 2026. NEVER use datetime.now() to resolve date
# presets ("This Month", "YTD") - today's real date is earlier than the end of
# the data, so relative presets computed from now() would show future-dated
# transactions during a live demo. Everything relative is computed from here.
AS_OF_DATE = date(2026, 12, 31)

DATA_START = date(2025, 1, 1)
DATA_END = date(2026, 12, 31)

# --- Business thresholds (all demo heuristics, clearly labelled) ----------
FORMULARY_TARGET_PCT = 92.0    # reference line on the compliance trend chart
SOB_OPPORTUNITY_PCT = 60.0     # top vendor below this share => opportunity
NEAR_EXPIRY_DAYS = 90          # already baked into the dataset's expiry flag
NON_MOVING_DAYS = 90           # no issue movement in this window
INVENTORY_DAYS_WINDOW = 30     # denominator for Inventory Days

# --- Formulary tiers ------------------------------------------------------
# READ OFF LOW-RESOLUTION SCREENSHOTS - confirm with the client before these
# labels are shown on screen. The codes are certain; the expansions are not.
FORMULARY_TIERS = ["I", "P1", "P2", "S1", "OOF"]
TIER_LABELS = {
    "I": "Innovator",
    "P1": "Preferred 1",
    "P2": "Preferred 2",
    "S1": "Substitute",
    "OOF": "Out of Formulary",
}
# Which tiers count towards share-of-business compliance.
SOB_COMPLIANT_TIERS = ["I", "P1"]

# --- Dimension values -----------------------------------------------------
STOCK_TAKE_GROUPS = ["Pharmacy", "General Store"]
PAYER_TYPES = ["Cash", "TPA", "Scheme"]
EPISODE_TYPES = ["Emergency", "Elective", "Day Care", "Follow Up"]

# --- CORS -----------------------------------------------------------------
# Local dev origins are always allowed. In production, set FRONTEND_ORIGIN to
# the deployed frontend URL - hardcoding it here would mean a redeploy every
# time the URL changes.
import os

ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
_deployed = os.environ.get("FRONTEND_ORIGIN")
if _deployed:
    ALLOWED_ORIGINS += [o.strip() for o in _deployed.split(",")]


# Active hospital units for this presentation. The synthetic network has 12
# units so the Region/Zone/Cluster hierarchy can be demoed in full later -
# this list just scopes what DataStore surfaces right now. Nothing else
# changes: switch this back to all 12 to bring the rest of the network back.
ACTIVE_UNITS = ["H010", "H011"]  # Pune, Goa

# --- Root cause analysis (RCA) --------------------------------------------
# Every threshold the RCA tab uses lives here. These are DISPLAY and FLAGGING
# rules, not business facts: the client should confirm them. None of them
# changes a calculated number - they only decide the label shown next to it.
RCA_TOP_N = 5                  # contributors listed per dimension (the rest are grouped as "All other")
RCA_MIN_HISTORY_MONTHS = 8     # fewer comparable months than this => no "is it unusual" verdict is given
RCA_Z_UNUSUAL = 2.0            # |z| >= this => "Unusual" versus the metric's own history
RCA_Z_WATCH = 1.0              # |z| >= this (below UNUSUAL) => "Watch"
RCA_CONCENTRATED_PCT = 60.0    # one value explains >= this % of the change => "Concentrated"
RCA_MODERATE_PCT = 30.0        # >= this % => "Moderate"; below => "Spread out"
RCA_MATERIAL_SHARE_PCT = 10.0  # KPI tree: a branch must explain >= this % of the change to be flagged
RCA_NEGLIGIBLE_DELTA = 1e-9    # |change| below this is treated as "no change" (shares are not computed)
RCA_MIN_RELATIVE_CHANGE_PCT = 0.25  # a net change smaller than this % of the comparison value is "flat": shares of it are not shown

# Stock classes used by the Inventory Days KPI tree. Each stock line is counted
# in exactly ONE class, the first that applies, so the classes add up to total
# stock. Order = precedence.
RCA_STOCK_CLASS_ORDER = ["Expired", "Near expiry", "Non-moving", "Healthy"]
