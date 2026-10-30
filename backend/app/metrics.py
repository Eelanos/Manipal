"""
THE metrics layer. Every number that appears on more than one page is computed
here and ONLY here.

The most important file in the backend: "Total Consumption Value" appears on
the Consumption page and again on the Formulary page. If two routers each
compute it themselves they will drift - a different null handling, a join that
fans out rows. The client opens two tabs, compares, and sees Rs 4.2 Cr against
Rs 4.4 Cr. At that point the demo is over.

Rule: routers call these functions. Routers never write their own .sum().
"""

import pandas as pd

from app.config import FORMULARY_TARGET_PCT, SOB_OPPORTUNITY_PCT


def total_value(df: pd.DataFrame, col: str = "Value") -> float:
    return float(df[col].sum()) if len(df) else 0.0


def total_qty(df: pd.DataFrame, col: str = "Qty") -> float:
    return float(df[col].sum()) if len(df) else 0.0


def safe_pct(numerator: float, denominator: float) -> float:
    """Percentage that returns 0.0 instead of exploding on an empty filter."""
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def consumption_kpis(df: pd.DataFrame) -> dict:
    val = total_value(df)
    ip = total_value(df[df["Patient_Type"] == "IP"])
    return {
        "total_value": val,
        "total_qty": total_qty(df),
        "ip_pct": safe_pct(ip, val),
        "op_pct": safe_pct(val - ip, val),
        "avg_per_txn": round(val / len(df), 2) if len(df) else 0.0,
        "txn_count": len(df),
    }


def monthly_trend(df: pd.DataFrame, value_col: str = "Value") -> pd.DataFrame:
    """Month-by-month totals. Used by every trend chart on every page."""
    if not len(df):
        return pd.DataFrame(columns=["Month_Start", value_col])
    return (
        df.groupby("Month_Start", as_index=False)[value_col]
        .sum()
        .sort_values("Month_Start")
    )


def year_over_year(df: pd.DataFrame, value_col: str = "Value") -> dict:
    """Two series keyed by month number, one per year, for the 2025-vs-2026
    overlaid line chart the spec asks for on multiple pages."""
    if not len(df):
        return {}
    t = df.copy()
    t["_y"] = t["Month_Start"].dt.year
    t["_m"] = t["Month_Start"].dt.month
    g = t.groupby(["_y", "_m"], as_index=False)[value_col].sum()
    return {
        int(y): grp.sort_values("_m")[["_m", value_col]]
        .rename(columns={"_m": "month", value_col: "value"})
        .to_dict("records")
        for y, grp in g.groupby("_y")
    }


def breakdown(df: pd.DataFrame, by: str, value_col: str = "Value",
              top_n: int | None = None) -> pd.DataFrame:
    """Generic 'value by dimension' aggregation, sorted descending."""
    if not len(df):
        return pd.DataFrame(columns=[by, value_col])
    g = (df.groupby(by, as_index=False)[value_col].sum()
           .sort_values(value_col, ascending=False))
    return g.head(top_n) if top_n else g


def formulary_kpis(df: pd.DataFrame) -> dict:
    val = total_value(df)
    on = total_value(df[df["Is_Formulary"] == True])
    off_items = df.loc[df["Is_Formulary"] == False, "Item_ID"].nunique()
    return {
        "compliance_pct": safe_pct(on, val),
        "on_formulary_value": on,
        "off_formulary_value": val - on,
        "off_formulary_items": int(off_items),
        "target_pct": FORMULARY_TARGET_PCT,
    }


def vendor_share_by_item(df: pd.DataFrame) -> pd.DataFrame:
    """Per item: each vendor's share of that item's purchase value.
    Feeds both SOB dashboards, so it lives here not in either router."""
    if not len(df):
        return pd.DataFrame(columns=["Item_ID", "Vendor_ID", "Value", "share_pct"])
    g = df.groupby(["Item_ID", "Vendor_ID"], as_index=False)["Value"].sum()
    totals = g.groupby("Item_ID")["Value"].transform("sum")
    g["share_pct"] = (g["Value"] / totals * 100).round(2)
    return g


def top_vendor_per_item(df: pd.DataFrame) -> pd.DataFrame:
    """The dominant vendor for each item, with its share."""
    g = vendor_share_by_item(df)
    if not len(g):
        return g
    return g.sort_values("share_pct", ascending=False).groupby("Item_ID").head(1)


def sob_opportunities(df: pd.DataFrame) -> pd.DataFrame:
    """Items where no single vendor holds SOB_OPPORTUNITY_PCT share.
    DEMO HEURISTIC - clearly labelled, easy to replace with a real rule."""
    top = top_vendor_per_item(df)
    if not len(top):
        return top
    top = top.copy()
    top["is_opportunity"] = top["share_pct"] < SOB_OPPORTUNITY_PCT
    return top


def sob_compliance(df: pd.DataFrame, targets: dict) -> pd.DataFrame:
    """Actual vs agreed vendor share, per item. targets is the FROZEN
    synthetic commitment. Actual is recomputed on filtered data; target never
    changes."""
    shares = vendor_share_by_item(df)
    if not len(shares):
        return pd.DataFrame(
            columns=["Item_ID", "Vendor_ID", "target_pct", "actual_pct",
                     "variance_pct", "Value", "on_target"])
    rows = []
    for item_id, t in targets.items():
        vendor_id = t["vendor_id"]
        m = shares[(shares["Item_ID"] == item_id) & (shares["Vendor_ID"] == vendor_id)]
        if not len(m):
            continue
        actual = float(m["share_pct"].iloc[0])
        target = float(t["target_sob_pct"])
        rows.append({
            "Item_ID": item_id,
            "Vendor_ID": vendor_id,
            "target_pct": target,
            "actual_pct": actual,
            "variance_pct": round(actual - target, 2),
            "Value": float(m["Value"].iloc[0]),
            "on_target": actual >= target,
        })
    return pd.DataFrame(rows)


def inventory_kpis(df: pd.DataFrame) -> dict:
    val = total_value(df, "Stock_Value")
    nm = total_value(df[df["Moving/Non Moving"] == "Non Moving"], "Stock_Value")
    return {
        "total_stock_value": val,
        "total_stock_qty": total_qty(df, "Stock_Qty"),
        "non_moving_pct": safe_pct(nm, val),
        "near_expiry_items": int((df["Expiry/Near Expiry"] == "Near Expiry").sum()),
        "expired_items": int((df["Expiry/Near Expiry"] == "Expired").sum()),
        "expired_value": total_value(
            df[df["Expiry/Near Expiry"] == "Expired"], "Stock_Value"),
    }


# ---------------------------------------------------------------------------
# Budget (plan vs actual)
# ---------------------------------------------------------------------------
def budget_by_month(budget_df: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly budget totals. ACTUAL is deliberately NOT read from this table -
    it comes from the consumption frame via monthly_trend(), so the number on
    the BUD-vs-ACT chart is the same number on the KPI card. Two sources for
    one metric is how a demo falls apart in front of a client.
    """
    if not len(budget_df):
        return pd.DataFrame(columns=["Month_Start", "Budget_Value"])
    return (budget_df.groupby("Month_Start", as_index=False)["Budget_Value"]
            .sum().sort_values("Month_Start"))


def budget_kpis(actual_value: float, budget_value: float) -> dict:
    """Utilisation and variance against plan."""
    return {
        "budget_value": budget_value,
        "utilisation_pct": safe_pct(actual_value, budget_value),
        "variance_value": actual_value - budget_value,
        "variance_pct": safe_pct(actual_value - budget_value, budget_value),
    }


# ---------------------------------------------------------------------------
# Inventory Days
# ---------------------------------------------------------------------------
# CLIENT-SUPPLIED DEFINITION:
#
#   Inventory Days = (Stock Value x days elapsed in the month)
#                    / (Consumption from the 1st of the month to that date)
#
# Month-to-date days of cover. On the 11th, "days elapsed" is 11. The window
# resets on the 1st of each calendar month.
#
# NOTE ON GRAIN: our inventory table holds month-END snapshots only (24 dates
# over two years), so we produce a MONTHLY series, not the daily one on their
# "Daily N Inventory" page. Daily stock positions would be needed for that.
def inventory_days(stock_value: float, consumption_mtd: float,
                   days_elapsed: int) -> float:
    if not consumption_mtd or not days_elapsed:
        return 0.0
    return round(stock_value * days_elapsed / consumption_mtd, 1)


def inventory_days_series(inv_df: pd.DataFrame,
                          cons_df: pd.DataFrame) -> pd.DataFrame:
    """One Inventory Days figure per stock snapshot date."""
    if not len(inv_df) or not len(cons_df):
        return pd.DataFrame(columns=["Date", "inventory_days"])
    rows = []
    for snap_date, grp in inv_df.groupby("Date"):
        month_start = snap_date.replace(day=1)
        mtd = cons_df[(cons_df["Date"] >= month_start)
                      & (cons_df["Date"] <= snap_date)]["Value"].sum()
        rows.append({
            "Date": snap_date,
            "inventory_days": inventory_days(
                float(grp["Stock_Value"].sum()), float(mtd), snap_date.day),
        })
    return pd.DataFrame(rows).sort_values("Date")


def his_consumption(cons_df: pd.DataFrame) -> dict:
    """
    HIS consumption split by implant / non-implant. Implants are high-value
    items that distort a consumption figure if left in, which is why their
    report shows both.
    """
    total = total_value(cons_df)
    implant = total_value(cons_df[cons_df["Is_Implant"] == True])  # noqa: E712
    return {
        "his_cons": total,
        "implant_cons": implant,
        "non_implant_cons": total - implant,
        "implant_pct": safe_pct(implant, total),
    }


# ---------------------------------------------------------------------------
# Share of Business (brand mix within a molecule)
# ---------------------------------------------------------------------------
# SOB here is NOT vendor consolidation. The hospital agrees commitments with
# manufacturers - "we will route X% of our volume in this molecule to your
# brand" - and SOB tracks whether prescribing actually delivers that.
#
# The lever is a conversation with a doctor, not a supplier contract, which is
# why the opportunity views break down by prescriber and by generic.
def sob_tier_mix(df: pd.DataFrame, compliant_tiers: list[str]) -> dict:
    """Headline split between preferred and non-preferred prescribing."""
    total = total_value(df)
    preferred = total_value(df[df["Formulary_Tier"].isin(compliant_tiers)])
    return {
        "total": total,
        "preferred_value": preferred,
        "non_preferred_value": total - preferred,
        "compliance_pct": safe_pct(preferred, total),
    }


def sob_tier_by_month(df: pd.DataFrame, tier_order: list[str]) -> list[dict]:
    """Tier share per month, as percentages summing to 100 - the stacked bar."""
    if not len(df):
        return []
    rows = []
    for month, grp in df.groupby("Month_Start"):
        tot = grp["Value"].sum()
        row = {"month": month.strftime("%b %y")}
        for t in tier_order:
            row[t] = safe_pct(grp.loc[grp["Formulary_Tier"] == t, "Value"].sum(), tot)
        rows.append(row)
    return rows


def sob_opportunity(df: pd.DataFrame, preferred_molecules: set,
                    compliant_tiers: list[str]) -> pd.DataFrame:
    """
    The switchable spend: consumption on a non-preferred brand WHERE a
    preferred brand exists for the same molecule.

    Consumption on a molecule with no preferred alternative is excluded - it
    is not an opportunity, there is nothing to switch to. Counting it would
    inflate the number and send someone chasing a conversation that cannot
    have an outcome.
    """
    if not len(df):
        return df
    return df[
        (~df["Formulary_Tier"].isin(compliant_tiers))
        & (df["Molecule"].isin(preferred_molecules))
    ]


def budget_inventory_days_series(inv_df: pd.DataFrame, budget_df: pd.DataFrame) -> pd.DataFrame:
    """
    Same Inventory Days formula as inventory_days_series, but against
    BUDGETED consumption instead of actual - the target/plan line for the
    Inventory Days Trend chart. Same idea as BUD vs ACT on Consumption.
    """
    if not len(inv_df) or not len(budget_df):
        return pd.DataFrame(columns=["Date", "budget_inventory_days"])
    rows = []
    for snap_date, grp in inv_df.groupby("Date"):
        month_start = snap_date.replace(day=1)
        mtd = budget_df[(budget_df["Date"] >= month_start)
                        & (budget_df["Date"] <= snap_date)]["Budget_Value"].sum()
        rows.append({
            "Date": snap_date,
            "budget_inventory_days": inventory_days(
                float(grp["Stock_Value"].sum()), float(mtd), snap_date.day),
        })
    return pd.DataFrame(rows).sort_values("Date")

def his_consumption_by_dept(cons_df: pd.DataFrame) -> dict:
    """Month -> department-wise consumption rows, for the drill-down modal."""
    out: dict[str, list[dict]] = {}
    for month, grp in cons_df.groupby("Month_Start"):
        dept = grp.groupby("Dept_Name", as_index=False)["Value"].sum()
        dept = dept.sort_values("Value", ascending=False)
        key = month.strftime("%b %y")
        out[key] = [
            {"Department": r["Dept_Name"], "Value": float(r["Value"])}
            for _, r in dept.iterrows()
        ]
    return out

def inventory_days_by_dept(inv_df: pd.DataFrame, cons_df: pd.DataFrame) -> dict:
    """Month -> department-wise stock value, for the Inventory Days drill-down."""
    out: dict[str, list[dict]] = {}
    for month, grp in inv_df.groupby("Month_Start"):
        dept = grp.groupby("Dept_Name", as_index=False)["Stock_Value"].sum()
        dept = dept.sort_values("Stock_Value", ascending=False)
        key = month.strftime("%b %y")
        out[key] = [
            {"Department": r["Dept_Name"], "Value": float(r["Stock_Value"])}
            for _, r in dept.iterrows()
        ]
    return out


def non_moving_by_dept(inv_df: pd.DataFrame) -> dict:
    """Month -> non-moving stock value by department, for the donut drill-down."""
    out: dict[str, list[dict]] = {}
    for month, grp in inv_df.groupby("Month_Start"):
        nm = grp[grp["Moving/Non Moving"] == "Non Moving"]
        dept = nm.groupby("Dept_Name", as_index=False)["Stock_Value"].sum()
        dept = dept[dept["Stock_Value"] > 0].sort_values("Stock_Value", ascending=False)
        key = month.strftime("%b %y")
        out[key] = [
            {"name": r["Dept_Name"], "value": float(r["Stock_Value"])}
            for _, r in dept.iterrows()
        ]
    return out


def expiry_risk_by_dept(inv_df: pd.DataFrame) -> dict:
    """Month -> near-expiry + expired stock value by department, for the donut drill-down."""
    out: dict[str, list[dict]] = {}
    for month, grp in inv_df.groupby("Month_Start"):
        risk = grp[grp["Expiry/Near Expiry"].isin(["Near Expiry", "Expired"])]
        dept = risk.groupby("Dept_Name", as_index=False)["Stock_Value"].sum()
        dept = dept[dept["Stock_Value"] > 0].sort_values("Stock_Value", ascending=False)
        key = month.strftime("%b %y")
        out[key] = [
            {"name": r["Dept_Name"], "value": float(r["Stock_Value"])}
            for _, r in dept.iterrows()
        ]
    return out

def consumption_by_item_for_location(df: pd.DataFrame) -> dict:
    """Store_Location -> item-wise consumption rows, for the location drill-down."""
    out: dict[str, list[dict]] = {}
    for loc, grp in df.groupby("Store_Location"):
        item = grp.groupby("Item_Name", as_index=False)["Value"].sum()
        item = item.sort_values("Value", ascending=False).head(15)
        out[str(loc)] = [
            {"Department": r["Item_Name"], "Value": float(r["Value"])}
            for _, r in item.iterrows()
        ]
    return out


def inventory_by_item_for_location(inv_snap: pd.DataFrame) -> dict:
    """Store_Location -> item-wise stock value rows, for the location drill-down."""
    out: dict[str, list[dict]] = {}
    for loc, grp in inv_snap.groupby("Store_Location"):
        item = grp.groupby("Item_Name", as_index=False)["Stock_Value"].sum()
        item = item.sort_values("Stock_Value", ascending=False).head(15)
        out[str(loc)] = [
            {"Department": r["Item_Name"], "Value": float(r["Stock_Value"])}
            for _, r in item.iterrows()
        ]
    return out

def closing_stock_by_dept(inv_df: pd.DataFrame) -> dict:
    """Month -> department-wise stock value, for the Closing Stock Ageing drill-down."""
    out: dict[str, list[dict]] = {}
    for month, grp in inv_df.groupby("Month_Start"):
        dept = grp.groupby("Dept_Name", as_index=False)["Stock_Value"].sum()
        dept = dept.sort_values("Stock_Value", ascending=False)
        key = month.strftime("%b %y")
        out[key] = [
            {"Department": r["Dept_Name"], "Value": float(r["Stock_Value"])}
            for _, r in dept.iterrows()
        ]
    return out

def stock_and_days_by_unit(inv_df: pd.DataFrame, cons_df: pd.DataFrame) -> dict:
    """Month -> one row per unit with its stock value and Inventory Days, for
    the Consumption Trend drill-down. Inventory Days is the same formula as the
    Inventory Days Trend (stock x days elapsed / consumption month-to-date),
    just worked out per unit instead of for the whole scope."""
    out: dict[str, list[dict]] = {}
    for month, grp in inv_df.groupby("Month_Start"):
        # Stock is a point-in-time measure: read the month's latest snapshot.
        snap_date = grp["Date"].max()
        snap = grp[grp["Date"] == snap_date]
        month_start = snap_date.replace(day=1)
        rows = []
        for unit, ugrp in snap.groupby("Unit_Name"):
            stock = float(ugrp["Stock_Value"].sum())
            mtd = cons_df[(cons_df["Unit_Name"] == unit)
                          & (cons_df["Date"] >= month_start)
                          & (cons_df["Date"] <= snap_date)]["Value"].sum()
            rows.append({
                "Unit": unit,
                "Stock": stock,
                "Inventory Days": inventory_days(stock, float(mtd), snap_date.day),
            })
        rows.sort(key=lambda r: r["Stock"], reverse=True)
        out[month.strftime("%b %y")] = rows
    return out

def off_formulary_items_by_month(df: pd.DataFrame) -> dict:
    """Month -> off-formulary item rows, for the compliance-trend drill-down."""
    out: dict[str, list[dict]] = {}
    off = df[df["Is_Formulary"] == False]  # noqa: E712
    for month, grp in off.groupby("Month_Start"):
        item = grp.groupby("Item_Name", as_index=False)["Value"].sum()
        item = item.sort_values("Value", ascending=False).head(15)
        key = month.strftime("%b %y")
        out[key] = [
            {"Department": r["Item_Name"], "Value": float(r["Value"])}
            for _, r in item.iterrows()
        ]
    return out


def ip_op_compliance_by_dept(df: pd.DataFrame) -> dict:
    """Month -> department-wise on/off-formulary value split, for the IP/OP drill-down."""
    out: dict[str, list[dict]] = {}
    for month, grp in df.groupby("Month_Start"):
        dept = (grp.groupby("Dept_Name", as_index=False)
                   .apply(lambda g: pd.Series({
                       "On_Formulary": g.loc[g["Is_Formulary"] == True, "Value"].sum(),  # noqa: E712
                       "Off_Formulary": g.loc[g["Is_Formulary"] == False, "Value"].sum(),  # noqa: E712
                   }), include_groups=False)
                   .reset_index())
        dept["Total"] = dept["On_Formulary"] + dept["Off_Formulary"]
        dept = dept.sort_values("Total", ascending=False)
        key = month.strftime("%b %y")
        out[key] = [
            {"Department": r["Dept_Name"], "Value": float(r["Total"])}
            for _, r in dept.iterrows()
        ]
    return out


def formulary_package_mix_by_month(df: pd.DataFrame, segments: list[tuple[str, str]]) -> dict:
    """Month -> segment (On/Off x Package/Non-Package) value breakdown, for the donut drill-down."""
    out: dict[str, list[dict]] = {}
    for month, grp in df.groupby("Month_Start"):
        key = month.strftime("%b %y")
        slices = []
        for status, pkg in segments:
            mask = (
                (grp["Is_Formulary"] == (status == "On-Formulary"))
                & (grp["Is_Package"] == (pkg == "Package"))
            )
            val = float(grp.loc[mask, "Value"].sum())
            if val > 0:
                slices.append({"name": f"{status} - {pkg}", "value": val})
        out[key] = slices
    return out

def molecule_brand_by_month(df: pd.DataFrame) -> dict:
    """Month -> molecule+brand consumption rows, for SOB Compliance month drill-downs."""
    out: dict[str, list[dict]] = {}
    for month, grp in df.groupby("Month_Start"):
        agg = (grp.groupby(["Molecule", "Item_Name"], as_index=False)["Value"].sum()
                  .sort_values("Value", ascending=False).head(15))
        key = month.strftime("%b %y")
        out[key] = [
            {"Department": f"{r['Molecule']} — {r['Item_Name']}", "Value": float(r["Value"])}
            for _, r in agg.iterrows()
        ]
    return out


def molecule_brand_by_tier(df: pd.DataFrame, tier_labels: dict) -> dict:
    """Tier label -> top molecule+brand rows, for the Overall Tier Mix donut drill-down."""
    out: dict[str, list[dict]] = {}
    for tier, grp in df.groupby("Formulary_Tier"):
        agg = (grp.groupby(["Molecule", "Item_Name"], as_index=False)["Value"].sum()
                  .sort_values("Value", ascending=False).head(15))
        key = f"{tier} - {tier_labels.get(tier, '')}"
        out[key] = [
            {"Department": f"{r['Molecule']} — {r['Item_Name']}", "Value": float(r["Value"])}
            for _, r in agg.iterrows()
        ]
    return out


def items_by_package_split(opp: pd.DataFrame) -> dict:
    """'Package'/'Non-Package' -> top item rows, for the package_split donut drill-down."""
    out: dict[str, list[dict]] = {}
    for label, mask in [("Package", opp["Is_Package"] == True),   # noqa: E712
                          ("Non-Package", opp["Is_Package"] == False)]:  # noqa: E712
        grp = opp[mask]
        agg = (grp.groupby("Item_Name", as_index=False)["Value"].sum()
                  .sort_values("Value", ascending=False).head(15))
        out[label] = [
            {"Department": r["Item_Name"], "Value": float(r["Value"])}
            for _, r in agg.iterrows()
        ]
    return out


def molecule_by_doctor(opp: pd.DataFrame) -> dict:
    """Doctor -> molecule-wise opportunity rows, for the by_doctor drill-down."""
    out: dict[str, list[dict]] = {}
    for doc, grp in opp.groupby("Doctor"):
        agg = (grp.groupby("Molecule", as_index=False)["Value"].sum()
                  .sort_values("Value", ascending=False).head(15))
        out[str(doc)] = [
            {"Department": r["Molecule"], "Value": float(r["Value"])}
            for _, r in agg.iterrows()
        ]
    return out


def doctor_brand_by_molecule(opp: pd.DataFrame) -> dict:
    """Molecule -> doctor+brand-wise opportunity rows, for the by_molecule drill-down."""
    out: dict[str, list[dict]] = {}
    for mol, grp in opp.groupby("Molecule"):
        agg = (grp.groupby(["Doctor", "Item_Name"], as_index=False)["Value"].sum()
                  .sort_values("Value", ascending=False).head(15))
        out[str(mol)] = [
            {"Department": f"{r['Doctor']} — {r['Item_Name']}", "Value": float(r["Value"])}
            for _, r in agg.iterrows()
        ]
    return out


def doctors_by_brand(opp: pd.DataFrame) -> dict:
    """Brand (Item_Name) -> doctor-wise opportunity rows, for the by_item drill-down."""
    out: dict[str, list[dict]] = {}
    for item, grp in opp.groupby("Item_Name"):
        agg = (grp.groupby("Doctor", as_index=False)["Value"].sum()
                  .sort_values("Value", ascending=False).head(15))
        out[str(item)] = [
            {"Department": r["Doctor"], "Value": float(r["Value"])}
            for _, r in agg.iterrows()
        ]
    return out