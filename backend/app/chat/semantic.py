"""
The semantic registry: what the chatbot is allowed to talk about and what each
word MEANS.

Nothing here is an answer or a data value. It is a declarative description of
the business vocabulary mapped onto the DataStore's columns:

  * Tables      - which DataStore frame, which date column, what grain
  * Dimensions  - things you can group/filter by ("department", "payer type")
  * Measures    - things you can compute ("consumption value", "SOB compliance %")

Why a registry instead of letting the model write pandas:
  * The model can only ever pick ids from this file (the plan schema is built
    from it), so it cannot invent a metric or a column.
  * A metric has exactly one definition, shared by every question. Where a
    dashboard already defines one (formulary compliance, SOB compliance,
    switchable opportunity, inventory days) this reuses the same config
    constants and the same metrics.py arithmetic, and tests/test_chat_parity.py
    proves the numbers equal the dashboards' for many filter combinations.
  * `validate_registry()` runs against the live data at startup: a renamed
    column or a missing category value fails loudly instead of silently
    returning wrong numbers.

Adding a metric or dimension = adding one entry below. No other file changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from app import config as cfg


# ---------------------------------------------------------------------------
# Expression building blocks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Ref:
    """A value resolved at runtime from config / the DataStore (never inlined)."""
    name: str


@dataclass(frozen=True)
class Cond:
    """Row filter used inside a measure definition. op: eq | ne | in | not_in."""
    column: str
    op: str
    value: Any


@dataclass(frozen=True)
class Agg:
    """Aggregate one column of one table. op: sum | count | nunique | mean."""
    table: str
    op: str
    column: Optional[str] = None
    where: tuple[Cond, ...] = ()


@dataclass(frozen=True)
class BinOp:
    """left <op> right, then multiplied by `scale` (100 turns a ratio into %).
    op: div | sub. Division by zero yields "no value", never 0 or infinity."""
    op: str
    left: "Expr"
    right: "Expr"
    scale: float = 1.0


@dataclass(frozen=True)
class InventoryDays:
    """
    Client-supplied definition (same as metrics.inventory_days):
      stock value x days elapsed in month / consumption month-to-date.
    Evaluated per stock snapshot date so it can be grouped like any measure.
    """
    stock: Agg
    consumption: Agg


Expr = Union[Agg, BinOp, InventoryDays]


@dataclass(frozen=True)
class Threshold:
    """A client/config-defined benchmark for a measure (never invented)."""
    value: Union[float, Ref]
    label: str
    higher_is_better: bool


# ---------------------------------------------------------------------------
# Registry entry types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TableDef:
    id: str
    attr: str              # attribute name on DataStore
    date_col: str
    kind: str              # "transactions" | "snapshot" | "monthly"
    label: str
    description: str


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    description: str
    columns: dict           # table id -> physical column. Missing table = unavailable there
    synonyms: tuple = ()
    # raw value -> display label. Dict, or callable(store) -> dict.
    value_labels: Any = None
    # extra phrases a user may type for a raw value: callable(store) -> {raw: [aliases]}
    aliases: Optional[Callable] = None
    null_label: Optional[str] = None     # display label for missing values
    order: Any = None                    # natural order of raw values (list/callable)
    featured: bool = False


@dataclass(frozen=True)
class Measure:
    id: str
    label: str
    description: str
    unit: str                            # currency | number | percent | days
    expr: Expr
    synonyms: tuple = ()
    featured: bool = False
    default_dims: tuple = ()             # dimensions that make a sensible breakdown
    threshold: Optional[Threshold] = None
    reference_line: Optional[Ref] = None  # drawn on trend charts


# ---------------------------------------------------------------------------
# Runtime references (config / store backed - the single link to dashboards)
# ---------------------------------------------------------------------------
REFS: dict[str, Callable] = {
    # Same constants the SOB dashboards use.
    "sob_compliant_tiers": lambda store: list(cfg.SOB_COMPLIANT_TIERS),
    # Same lookup the SOB dashboards use (molecules that have a preferred brand).
    "preferred_molecules": lambda store: sorted(store.preferred_molecules),
    "formulary_target_pct": lambda store: cfg.FORMULARY_TARGET_PCT,
}


def resolve_ref(ref: Ref, store) -> Any:
    return REFS[ref.name](store)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
TABLES: dict[str, TableDef] = {t.id: t for t in [
    TableDef("consumption", "consumption", "Date", "transactions",
             "Consumption",
             "Items issued/consumed for patients: one row per issue, with "
             "doctor, patient type, payer, formulary tier, revenue and cost."),
    TableDef("inventory", "inventory", "Date", "snapshot",
             "Inventory stock",
             "Month-END stock snapshots by batch. Stock is a point-in-time "
             "quantity: values from different months must never be added up."),
    TableDef("purchase", "purchase", "PO_Date", "transactions",
             "Purchases",
             "Purchase orders by vendor, with status Received or In-Transit. "
             "Has no department."),
    TableDef("movement", "movement", "Date", "transactions",
             "Stock movement",
             "Receipts, issues and transfers in units (quantity only, no value). "
             "Has no department."),
    TableDef("budget", "budget", "Date", "monthly",
             "Budget",
             "Monthly consumption budget by unit and department. Has no stock "
             "take group."),
]}


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
def _tier_labels(store) -> dict:
    return {code: f"{code} - {name}" for code, name in cfg.TIER_LABELS.items()}


def _tier_aliases(store) -> dict:
    return {code: [code, name] for code, name in cfg.TIER_LABELS.items()}


def _tier_order(store) -> list:
    return list(cfg.FORMULARY_TIERS)


def _unit_labels(store) -> dict:
    u = store.units
    return {r["Unit_ID"]: f"{r['Cluster']} ({r['Unit_Name']})" for _, r in u.iterrows()}


def _unit_aliases(store) -> dict:
    u = store.units
    return {r["Unit_ID"]: [r["Unit_ID"], r["Unit_Name"], r["Cluster"]]
            for _, r in u.iterrows()}


def _bool_labels(true_label: str, false_label: str) -> Callable:
    return lambda store: {True: true_label, False: false_label}


_ALL_FACT = ("consumption", "inventory", "purchase", "movement", "budget")

DIMENSIONS: dict[str, Dimension] = {d.id: d for d in [
    Dimension("unit", "Hospital unit",
              "Hospital unit (site). Values are shown as 'City (CODE)'.",
              {t: "Unit_ID" for t in _ALL_FACT},
              synonyms=("hospital", "site", "location of hospital", "branch"),
              value_labels=_unit_labels, aliases=_unit_aliases, featured=True),
    Dimension("cluster", "Cluster", "Hospital cluster (city group).",
              {t: "Cluster" for t in _ALL_FACT}),
    Dimension("zone", "Zone", "Hospital zone.",
              {t: "Zone" for t in _ALL_FACT}),
    Dimension("region", "Region", "Hospital region.",
              {t: "Region" for t in _ALL_FACT}),
    Dimension("department", "Department",
              "Clinical department (Cardiology, Oncology, ...). Not available "
              "for purchases or stock movement.",
              {"consumption": "Dept_Name", "inventory": "Dept_Name",
               "budget": "Dept_Name"},
              synonyms=("dept", "speciality department", "clinical department"),
              featured=True),
    Dimension("stock_take_group", "Stock take group",
              "Pharmacy (drugs) vs General Store (consumables). Not available "
              "for budget.",
              {"consumption": "Stock Take Group", "inventory": "Stock Take Group",
               "purchase": "Stock Take Group", "movement": "Stock Take Group"},
              synonyms=("store type", "pharmacy vs general store", "stock group"),
              featured=True),
    Dimension("category", "Item category",
              "Pharmacy or General Consumable (mirrors stock take group).",
              {"consumption": "Category", "inventory": "Category",
               "purchase": "Category"}),
    Dimension("item", "Item (brand)", "Individual item / brand name.",
              {t: "Item_Name" for t in ("consumption", "inventory", "purchase", "movement")},
              synonyms=("product", "brand", "sku", "drug", "consumable")),
    Dimension("molecule", "Molecule (generic)",
              "Generic/molecule an item belongs to. Several brands share a molecule.",
              {"consumption": "Molecule", "inventory": "Molecule", "purchase": "Molecule"},
              synonyms=("generic", "salt", "composition")),
    Dimension("formulary_tier", "Formulary tier",
              "Tier of the item: I = Innovator, P1/P2 = Preferred, S1 = "
              "Substitute, OOF = Out of Formulary. Preferred-brand (SOB) "
              "tiers are I and P1.",
              {"consumption": "Formulary_Tier", "inventory": "Formulary_Tier",
               "purchase": "Formulary_Tier"},
              synonyms=("tier", "brand tier", "sob tier"),
              value_labels=_tier_labels, aliases=_tier_aliases, order=_tier_order,
              featured=True),
    Dimension("formulary_status", "Formulary status",
              "Whether the item is on or off the hospital formulary.",
              {"consumption": "Is_Formulary"},
              synonyms=("on formulary", "off formulary", "formulary"),
              value_labels=_bool_labels("On Formulary", "Off Formulary")),
    Dimension("doctor", "Doctor (prescriber)", "Prescribing doctor.",
              {"consumption": "Doctor"},
              synonyms=("prescriber", "physician", "consultant")),
    Dimension("specialty", "Doctor specialty", "Specialty of the prescribing doctor.",
              {"consumption": "Specialty"}, synonyms=("speciality",)),
    Dimension("patient_type", "Patient type", "IP (inpatient) or OP (outpatient).",
              {"consumption": "Patient_Type"},
              synonyms=("ip op", "inpatient outpatient", "ip vs op")),
    Dimension("payer_type", "Payer type", "Cash, TPA or Scheme.",
              {"consumption": "Payer_Type"},
              synonyms=("payer", "payment type", "insurance type"), featured=True),
    Dimension("episode_type", "Episode type",
              "Emergency, Elective, Day Care or Follow Up.",
              {"consumption": "Episode_Type"}, synonyms=("episode", "visit type")),
    Dimension("package_status", "Package status",
              "Package (bundled-price case, hospital absorbs drug cost) vs Non-Package.",
              {"consumption": "Is_Package"},
              synonyms=("package", "closed package", "bundled"),
              value_labels=_bool_labels("Package", "Non-Package")),
    Dimension("implant_status", "Implant status", "Implant vs non-implant items.",
              {"consumption": "Is_Implant", "inventory": "Is_Implant"},
              synonyms=("implant",), value_labels=_bool_labels("Implant", "Non-Implant")),
    Dimension("essential_status", "Essential status", "Essential vs non-essential items.",
              {"consumption": "Is_Essential", "inventory": "Is_Essential"},
              synonyms=("essential",),
              value_labels=_bool_labels("Essential", "Non-Essential")),
    Dimension("store_location", "Store location",
              "Physical store/location inside a hospital (e.g. a cath-lab store).",
              {"consumption": "Store_Location", "inventory": "Store_Location"},
              synonyms=("store", "location", "pharmacy location")),
    Dimension("ageing", "Stock ageing bucket",
              "Age of stock since GRN: Below 30, 30 - 60, 60 - 90, Above 90 days.",
              {"inventory": "Ageing"}, synonyms=("age", "stock age", "ageing days"),
              order=lambda store: ["Below 30", "30 - 60", "60 - 90", "Above 90"]),
    Dimension("expiry_status", "Expiry status",
              "Near Expiry, Expired, or not flagged.",
              {"inventory": "Expiry/Near Expiry"},
              synonyms=("expiry", "near expiry", "expired"),
              null_label="Not near expiry"),
    Dimension("movement_status", "Moving / non-moving",
              "Whether stock has moved recently (Moving) or not (Non Moving).",
              {"inventory": "Moving/Non Moving"},
              synonyms=("non moving", "slow moving", "dead stock")),
    Dimension("vendor", "Vendor", "Supplier on the purchase order.",
              {"purchase": "Vendor_Name"}, synonyms=("supplier",)),
    Dimension("po_status", "Purchase order status", "Received or In-Transit.",
              {"purchase": "Status"}, synonyms=("order status", "po status")),
    Dimension("movement_type", "Movement type", "Receipt, Issue or Transfer.",
              {"movement": "Movement_Type"}, synonyms=("stock movement type",)),
]}


# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------
def _sum(table: str, col: str, *where: Cond) -> Agg:
    return Agg(table, "sum", col, tuple(where))


def _count(table: str, *where: Cond) -> Agg:
    return Agg(table, "count", None, tuple(where))


def _nunique(table: str, col: str, *where: Cond) -> Agg:
    return Agg(table, "nunique", col, tuple(where))


def _pct(num: Expr, den: Expr) -> BinOp:
    return BinOp("div", num, den, 100.0)


_C_VAL = _sum("consumption", "Value")
_C_VAL_ALL_TIERS_PREFERRED = _sum(
    "consumption", "Value",
    Cond("Formulary_Tier", "in", Ref("sob_compliant_tiers")))
_C_VAL_NON_PREFERRED = _sum(
    "consumption", "Value",
    Cond("Formulary_Tier", "not_in", Ref("sob_compliant_tiers")))
_C_VAL_SWITCHABLE = _sum(
    "consumption", "Value",
    Cond("Formulary_Tier", "not_in", Ref("sob_compliant_tiers")),
    Cond("Molecule", "in", Ref("preferred_molecules")))
_C_VAL_ONFORM = _sum("consumption", "Value", Cond("Is_Formulary", "eq", True))
_C_VAL_OFFFORM = _sum("consumption", "Value", Cond("Is_Formulary", "eq", False))
_C_VAL_IMPLANT = _sum("consumption", "Value", Cond("Is_Implant", "eq", True))
_C_VAL_NONIMPLANT = _sum("consumption", "Value", Cond("Is_Implant", "eq", False))
_C_VAL_IP = _sum("consumption", "Value", Cond("Patient_Type", "eq", "IP"))
_C_REV = _sum("consumption", "Revenue")
_C_COST = _sum("consumption", "Cost")

_I_VAL = _sum("inventory", "Stock_Value")
_I_NONMOVING = _sum("inventory", "Stock_Value", Cond("Moving/Non Moving", "eq", "Non Moving"))
_I_NEAR = _sum("inventory", "Stock_Value", Cond("Expiry/Near Expiry", "eq", "Near Expiry"))
_I_EXPIRED = _sum("inventory", "Stock_Value", Cond("Expiry/Near Expiry", "eq", "Expired"))
_I_ESSENTIAL = _sum("inventory", "Stock_Value", Cond("Is_Essential", "eq", True))

_B_VAL = _sum("budget", "Budget_Value")

MEASURES: dict[str, Measure] = {m.id: m for m in [
    # ---- Consumption ------------------------------------------------------
    Measure("consumption_value", "Consumption value",
            "Total value of items consumed (issued) in the period. The "
            "dashboards call this 'Total Consumption Value' / 'HIS Consumption'.",
            "currency", _C_VAL, ("spend", "usage", "consumption", "his consumption",
                                 "total consumption", "cons"),
            featured=True, default_dims=("department", "unit", "payer_type")),
    Measure("consumption_qty", "Consumption quantity",
            "Total units consumed.", "number", _sum("consumption", "Qty"),
            ("units consumed", "quantity consumed", "volume")),
    Measure("consumption_txn_count", "Consumption transactions",
            "Number of consumption (issue) transactions.", "number",
            _count("consumption"), ("transactions", "issues", "number of issues")),
    Measure("avg_value_per_txn", "Average value per transaction",
            "Consumption value divided by number of transactions.", "currency",
            BinOp("div", _C_VAL, _count("consumption")), ("average transaction value",)),
    Measure("patient_count", "Distinct patients",
            "Number of distinct patients with consumption.", "number",
            _nunique("consumption", "Patient_ID"), ("patients", "unique patients")),
    Measure("items_consumed", "Distinct items consumed",
            "Number of distinct items consumed.", "number",
            _nunique("consumption", "Item_ID"), ("number of items", "item count")),
    Measure("ip_share_pct", "IP share of consumption (%)",
            "Share of consumption value that is inpatient (IP).", "percent",
            _pct(_C_VAL_IP, _C_VAL), ("inpatient share", "ip share")),
    Measure("implant_value", "Implant consumption value",
            "Consumption value of implant items.", "currency", _C_VAL_IMPLANT,
            ("implants",)),
    Measure("non_implant_value", "Non-implant consumption value",
            "Consumption value excluding implants (dashboard: 'HIS Non-Implant Cons').",
            "currency", _C_VAL_NONIMPLANT, ("his non implant", "non implant cons")),
    Measure("implant_share_pct", "Implant share of consumption (%)",
            "Share of consumption value that is implants.", "percent",
            _pct(_C_VAL_IMPLANT, _C_VAL)),
    Measure("revenue", "Revenue",
            "Revenue recorded against consumption.", "currency", _C_REV,
            ("income", "billing", "billed")),
    Measure("cost", "Cost", "Cost recorded against consumption.", "currency", _C_COST,
            ("cogs", "cost of consumption")),
    Measure("margin", "Margin (revenue - cost)", "Revenue minus cost.", "currency",
            BinOp("sub", _C_REV, _C_COST), ("profit", "gross margin value")),
    Measure("margin_pct", "Margin (%)", "(Revenue - cost) / revenue.", "percent",
            _pct(BinOp("sub", _C_REV, _C_COST), _C_REV), ("margin percent", "profit margin")),
    # ---- Formulary --------------------------------------------------------
    Measure("on_formulary_value", "On-formulary consumption value",
            "Consumption value of items that are on the formulary.", "currency",
            _C_VAL_ONFORM),
    Measure("off_formulary_value", "Off-formulary consumption value",
            "Consumption value of items that are off the formulary.", "currency",
            _C_VAL_OFFFORM, ("non formulary value",)),
    Measure("formulary_compliance_pct", "Formulary compliance (%)",
            "Share of consumption value on formulary items. Dashboard: "
            "'Formulary Compliance'.", "percent",
            _pct(_C_VAL_ONFORM, _C_VAL), ("formulary adherence", "formulary compliance"),
            featured=True, default_dims=("department", "patient_type", "doctor"),
            threshold=Threshold(Ref("formulary_target_pct"), "formulary compliance target", True),
            reference_line=Ref("formulary_target_pct")),
    Measure("off_formulary_item_count", "Off-formulary items consumed",
            "Number of distinct off-formulary items consumed.", "number",
            _nunique("consumption", "Item_ID", Cond("Is_Formulary", "eq", False))),
    # ---- SOB ---------------------------------------------------------------
    Measure("preferred_brand_value", "Preferred-brand consumption value",
            "Consumption value on preferred (SOB-compliant) tiers.", "currency",
            _C_VAL_ALL_TIERS_PREFERRED, ("sob preferred value",)),
    Measure("non_preferred_value", "Non-preferred consumption value",
            "Consumption value on non-preferred tiers.", "currency",
            _C_VAL_NON_PREFERRED),
    Measure("sob_compliance_pct", "SOB compliance (%)",
            "Share of consumption value on preferred (SOB-compliant) tiers. "
            "Also called preferred-brand adherence when broken down by doctor. "
            "Dashboard: 'SOB Compliance'.", "percent",
            _pct(_C_VAL_ALL_TIERS_PREFERRED, _C_VAL),
            ("sob", "share of business", "preferred brand adherence", "sob compliance"),
            featured=True, default_dims=("doctor", "payer_type", "department")),
    Measure("switchable_opportunity_value", "Switchable SOB opportunity",
            "Consumption on a non-preferred brand where a preferred brand "
            "exists for the same molecule - the value that could be switched. "
            "Dashboard: 'SOB Opportunities'.", "currency", _C_VAL_SWITCHABLE,
            ("sob opportunity", "switchable spend", "opportunity", "switching opportunity"),
            featured=True, default_dims=("doctor", "molecule", "item")),
    Measure("switchable_opportunity_pct", "Switchable opportunity (% of consumption)",
            "Switchable SOB opportunity as a share of total consumption value.",
            "percent", _pct(_C_VAL_SWITCHABLE, _C_VAL)),
    # ---- Inventory (point-in-time) ----------------------------------------
    Measure("stock_value", "Inventory (stock) value",
            "Value of stock on hand at the snapshot date (latest snapshot in "
            "the period unless grouped by time).", "currency", _I_VAL,
            ("inventory value", "stock", "inventory", "closing stock"),
            featured=True, default_dims=("department", "ageing", "stock_take_group")),
    Measure("stock_qty", "Stock quantity", "Units of stock on hand at the snapshot date.",
            "number", _sum("inventory", "Stock_Qty"), ("inventory quantity",)),
    Measure("in_transit_stock_value", "Stock in transit (inventory)",
            "Value ordered but not yet received, as recorded on the inventory "
            "snapshot. Dashboard: 'Stock in Transit'.", "currency",
            _sum("inventory", "In_Transit_Value"), ("stock in transit", "in transit")),
    Measure("non_moving_stock_value", "Non-moving stock value",
            "Value of stock flagged Non Moving.", "currency", _I_NONMOVING,
            ("dead stock value", "slow moving value")),
    Measure("non_moving_pct", "Non-moving stock (%)",
            "Share of stock value that is non-moving.", "percent",
            _pct(_I_NONMOVING, _I_VAL), ("non moving percent", "dead stock percent"),
            default_dims=("department", "ageing")),
    Measure("near_expiry_value", "Near-expiry stock value",
            "Value of stock flagged Near Expiry.", "currency", _I_NEAR),
    Measure("expired_value", "Expired stock value", "Value of stock flagged Expired.",
            "currency", _I_EXPIRED),
    Measure("expiry_risk_pct", "Expiry risk (% of stock)",
            "Near-expiry plus expired stock as a share of stock value.", "percent",
            _pct(BinOp("sub", _I_VAL, _sum("inventory", "Stock_Value",
                 Cond("Expiry/Near Expiry", "not_in", ("Near Expiry", "Expired")))), _I_VAL),
            ("expiry risk", "expiry exposure")),
    Measure("essential_stock_pct", "Essential stock (%)",
            "Share of stock value that is essential items.", "percent",
            _pct(_I_ESSENTIAL, _I_VAL)),
    Measure("inventory_days", "Inventory days",
            "Client definition: stock value x days elapsed in the month / "
            "consumption month-to-date. Evaluated at the stock snapshot date.",
            "days", InventoryDays(_I_VAL, _C_VAL),
            ("days of inventory", "stock days", "days of cover", "inventory cover"),
            featured=True, default_dims=("department",)),
    # ---- Purchases ---------------------------------------------------------
    Measure("purchase_value", "Purchase value", "Total value of purchase orders.",
            "currency", _sum("purchase", "Value"), ("purchases", "procurement", "po value",
                                                   "purchase spend"),
            featured=True, default_dims=("vendor", "stock_take_group")),
    Measure("purchase_qty", "Purchase quantity", "Units on purchase orders.", "number",
            _sum("purchase", "Qty")),
    Measure("po_count", "Purchase order lines", "Number of purchase order lines.",
            "number", _count("purchase"), ("number of pos", "po count")),
    Measure("purchase_in_transit_value", "Purchase orders in transit (value)",
            "Value of purchase orders with status In-Transit (ordered, not "
            "received). Different from the inventory 'stock in transit' figure.",
            "currency", _sum("purchase", "Value", Cond("Status", "eq", "In-Transit")),
            ("open po value", "pending deliveries", "in transit purchases")),
    Measure("vendor_count", "Distinct vendors", "Number of distinct vendors.", "number",
            _nunique("purchase", "Vendor_ID"), ("number of vendors",)),
    # ---- Stock movement ----------------------------------------------------
    Measure("movement_qty", "Stock movement quantity",
            "Units moved (receipts, issues, transfers).", "number",
            _sum("movement", "Qty"), ("movement", "units moved")),
    # ---- Budget ------------------------------------------------------------
    Measure("budget_value", "Budget", "Planned consumption budget.", "currency", _B_VAL,
            ("planned consumption", "plan")),
    Measure("budget_utilisation_pct", "Budget utilisation (%)",
            "Actual consumption / budget.", "percent",
            _pct(_C_VAL, _B_VAL), ("budget utilization", "budget vs actual",
                                   "actual vs budget", "budget attainment"),
            featured=True, default_dims=("department", "unit"),
            threshold=Threshold(100.0, "budget (100%)", False)),
    Measure("budget_variance_value", "Budget variance (actual - budget)",
            "Actual consumption minus budget; positive = over budget.", "currency",
            BinOp("sub", _C_VAL, _B_VAL), ("over budget", "under budget",
                                           "budget overrun", "budget variance")),
    Measure("budget_variance_pct", "Budget variance (%)",
            "(Actual - budget) / budget.", "percent",
            _pct(BinOp("sub", _C_VAL, _B_VAL), _B_VAL)),
]}


# ---------------------------------------------------------------------------
# Helpers over the registry
# ---------------------------------------------------------------------------
def expr_aggs(expr: Expr) -> list[Agg]:
    """Every Agg an expression is built from."""
    if isinstance(expr, Agg):
        return [expr]
    if isinstance(expr, BinOp):
        return expr_aggs(expr.left) + expr_aggs(expr.right)
    if isinstance(expr, InventoryDays):
        return [expr.stock, expr.consumption]
    raise TypeError(f"Unknown expression {expr!r}")


def measure_tables(m: Measure) -> set[str]:
    return {a.table for a in expr_aggs(m.expr)}


def dimension_supported_on(dim: Dimension, tables: set[str]) -> bool:
    return all(t in dim.columns for t in tables)


def validate_registry(store) -> list[str]:
    """
    Check every column / literal the registry mentions against the LIVE data.
    Returns a list of problems (empty = healthy). Called at startup so a
    schema change breaks loudly here, not silently in an answer.
    """
    problems: list[str] = []
    frames = {}
    for t in TABLES.values():
        df = getattr(store, t.attr, None)
        if df is None:
            problems.append(f"table '{t.id}': DataStore has no attribute '{t.attr}'")
            continue
        frames[t.id] = df
        if t.date_col not in df.columns:
            problems.append(f"table '{t.id}': missing date column '{t.date_col}'")

    for d in DIMENSIONS.values():
        for t, col in d.columns.items():
            if t not in frames:
                problems.append(f"dimension '{d.id}': unknown table '{t}'")
            elif col not in frames[t].columns:
                problems.append(f"dimension '{d.id}': column '{col}' not in table '{t}'")
            elif frames[t][col].isna().all():
                problems.append(f"dimension '{d.id}': column '{col}' in '{t}' is entirely empty")
        if callable(d.value_labels):
            labels = d.value_labels(store)
            for t, col in d.columns.items():
                if t in frames and col in frames[t].columns:
                    present = set(frames[t][col].dropna().unique())
                    unknown = present - set(labels)
                    if unknown:
                        problems.append(
                            f"dimension '{d.id}': values {sorted(map(str, unknown))[:5]} "
                            f"in '{t}.{col}' have no label")

    def check_cond(c: Cond, table: str, where: str):
        df = frames.get(table)
        if df is None or c.column not in df.columns:
            problems.append(f"{where}: column '{c.column}' not in table '{table}'")
            return
        vals = c.value
        if isinstance(vals, Ref):
            if vals.name not in REFS:
                problems.append(f"{where}: unknown Ref '{vals.name}'")
            return
        present = set(df[c.column].dropna().unique())
        wanted = vals if isinstance(vals, (list, tuple, set)) else [vals]
        missing = [w for w in wanted if w not in present]
        if missing and c.op in ("eq", "in"):
            problems.append(f"{where}: value(s) {missing} never occur in {table}.{c.column}")

    for m in MEASURES.values():
        for a in expr_aggs(m.expr):
            if a.table not in frames:
                problems.append(f"measure '{m.id}': unknown table '{a.table}'")
                continue
            if a.op not in ("sum", "count", "nunique", "mean"):
                problems.append(f"measure '{m.id}': bad agg op '{a.op}'")
            if a.op != "count":
                if a.column not in frames[a.table].columns:
                    problems.append(f"measure '{m.id}': column '{a.column}' not in '{a.table}'")
            for c in a.where:
                check_cond(c, a.table, f"measure '{m.id}'")
        if m.unit not in ("currency", "number", "percent", "days"):
            problems.append(f"measure '{m.id}': bad unit '{m.unit}'")
        if isinstance(m.threshold, Threshold) and isinstance(m.threshold.value, Ref):
            if m.threshold.value.name not in REFS:
                problems.append(f"measure '{m.id}': unknown threshold Ref")
    return problems


def is_point_in_time(m: Measure) -> bool:
    """True for stock-type measures that must never be summed across dates."""
    return any(TABLES[a.table].kind == "snapshot" for a in expr_aggs(m.expr))
