"""
KPI trees ("what is this number made of, and which branch moved?").

A tree writes a KPI out as the quantities it is calculated from. The engine
walks it for a month and a comparison, and for every branch reports:

  - the branch's own value now and in the comparison month
  - its IMPACT: how many points/days of the KPI's change it accounts for
  - whether its own move is unusual against its own history
  - the same impact split by dimension (department, doctor, item...)

Impacts are exact. Each KPI is a formula of a few sums, and the change in the
KPI is rewritten as a sum of (coefficient x change in one quantity):

  Formulary compliance  = 100 - 100*Off/Total
      change = -100/Total1 * dOff   +   100*(Off0/Total0)/Total1 * dTotal
               (off-formulary spend)     (total consumption)

  Inventory days = Stock * DaysInMonth / Consumption
      change = (D1/C1) * dStock  -  (days0/C1) * dConsumption  +  S0*(D1-D0)/C1
               (stock)              (consumption)                 (calendar)

Stock is split into classes that add up to total stock (see
config.RCA_STOCK_CLASS_ORDER); consumption into inpatient / outpatient.

The structure of a tree is the one piece of business knowledge written down
here (what a KPI is made of). It is not data. Thresholds that decide a branch's
flag live in config.py, and the client should confirm them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from app.config import (RCA_CONCENTRATED_PCT, RCA_MATERIAL_SHARE_PCT, RCA_MODERATE_PCT,
                        RCA_NEGLIGIBLE_DELTA, RCA_STOCK_CLASS_ORDER, RCA_TOP_N)
from app.filters import Filters
from app.rca import evidence as ev
from app.rca.dims import DIMS, has_dim
from app.rca.engine import (fmt_delta, fmt_value, get_measure, is_flat, make_base, months_available,
                            num, pattern_of, parse_month)
from app.rca.measures import (MEASURES, RcaError, Scope, align, at, long, stock_class, total)

TREE_COMPARES = ("prior_month", "same_month_last_year")
TREE_METRICS = ("formulary_compliance", "inventory_days")

_CONS_SPLITS = ("department", "doctor", "item", "unit", "payer", "store")
_INV_SPLITS = ("department", "item", "unit", "store", "category", "stock_group")


@dataclass
class Node:
    id: str
    label: str
    how: str                                   # one line: how it relates to its parent
    table: str | None = None                   # "cons" | "inv" | None (calendar effect)
    col: str | None = None
    mask: Callable[[pd.DataFrame], pd.Series] | None = None
    k: Callable[[dict], float] | None = None   # impact on the KPI per unit of change in this quantity
    split_dims: tuple[str, ...] = ()
    children: list["Node"] = field(default_factory=list)
    fixed_impact: Callable[[dict], float] | None = None   # for effects that are not a quantity


# --------------------------------------------------------------------------
# Tree definitions
# --------------------------------------------------------------------------
def _compliance_tree() -> Node:
    return Node(
        id="root", label="Formulary compliance", how="100% minus the off-formulary share of spend",
        children=[
            Node("off", "Off-formulary spend", "More off-formulary spend lowers compliance",
                 table="cons", col="Value", mask=lambda d: ~(d["Is_Formulary"] == True),  # noqa: E712
                 k=lambda T: -100.0 / T["D1"], split_dims=_CONS_SPLITS),
            Node("total", "Total consumption", "Compliance is a share, so a change in total spend moves it too",
                 table="cons", col="Value", mask=None,
                 k=lambda T: 100.0 * (T["N0"] / T["D0"]) / T["D1"], split_dims=_CONS_SPLITS,
                 children=[
                     Node("total_ip", "Inpatient (IP) consumption", "", table="cons", col="Value",
                          mask=lambda d: d["Patient_Type"] == "IP",
                          k=lambda T: 100.0 * (T["N0"] / T["D0"]) / T["D1"], split_dims=_CONS_SPLITS),
                     Node("total_op", "Outpatient (OP) consumption", "", table="cons", col="Value",
                          mask=lambda d: d["Patient_Type"] == "OP",
                          k=lambda T: 100.0 * (T["N0"] / T["D0"]) / T["D1"], split_dims=_CONS_SPLITS),
                 ]),
        ])


def _days_tree() -> Node:
    stock_k = lambda T: T["D1"] / T["C1"]
    cons_k = lambda T: -(T["S0"] * T["D0"] / T["C0"]) / T["C1"]
    classes = [
        Node(f"stock_{c.lower().replace(' ', '_').replace('-', '_')}", f"{c} stock", "", table="inv",
             col="Stock_Value", mask=(lambda cls: (lambda d: d["_cls"] == cls))(c), k=stock_k,
             split_dims=_INV_SPLITS)
        for c in RCA_STOCK_CLASS_ORDER
    ]
    return Node(
        id="root", label="Inventory days", how="Stock value x days in month / consumption",
        children=[
            Node("stock", "Stock value (month-end)", "More stock means more days of cover",
                 table="inv", col="Stock_Value", mask=None, k=stock_k, split_dims=_INV_SPLITS, children=classes),
            Node("cons", "Consumption", "More consumption means fewer days of cover",
                 table="cons", col="Value", mask=None, k=cons_k, split_dims=_CONS_SPLITS,
                 children=[
                     Node("cons_ip", "Inpatient (IP) consumption", "", table="cons", col="Value",
                          mask=lambda d: d["Patient_Type"] == "IP", k=cons_k, split_dims=_CONS_SPLITS),
                     Node("cons_op", "Outpatient (OP) consumption", "", table="cons", col="Value",
                          mask=lambda d: d["Patient_Type"] == "OP", k=cons_k, split_dims=_CONS_SPLITS),
                 ]),
            Node("calendar", "Days in month", "Months have different lengths",
                 fixed_impact=lambda T: T["S0"] * (T["D1"] - T["D0"]) / T["C1"]),
        ])


_BUILDERS = {"formulary_compliance": _compliance_tree, "inventory_days": _days_tree}


# --------------------------------------------------------------------------
# Walk
# --------------------------------------------------------------------------
def _totals(key: str, sc: Scope, m, bm) -> dict:
    if key == "formulary_compliance":
        spec = {"D": ("Value", None), "N": ("Value", lambda d: ~(d["Is_Formulary"] == True))}  # noqa: E712
        lg = long(sc.cons_full, None, spec)
        T = {"D1": total(lg, m, "D"), "N1": total(lg, m, "N"),
             "D0": total(lg, bm, "D"), "N0": total(lg, bm, "N")}
        if T["D1"] <= 0 or T["D0"] <= 0:
            raise RcaError("No consumption data for one of the two months in this scope.")
        return T
    s = long(sc.inv_full, None, {"S": ("Stock_Value", None)})
    c = long(sc.cons_full, None, {"C": ("Value", None)})
    T = {"S1": total(s, m, "S"), "S0": total(s, bm, "S"), "C1": total(c, m, "C"), "C0": total(c, bm, "C"),
         "D1": float(m.days_in_month), "D0": float(bm.days_in_month)}
    if min(T["S1"], T["S0"], T["C1"], T["C0"]) <= 0:
        raise RcaError("No stock or consumption data for one of the two months in this scope.")
    return T


def _flag(share: float | None, evd: dict) -> str:
    if share is None or abs(share) < RCA_MATERIAL_SHARE_PCT:
        return "minor"
    if not evd.get("available"):
        return "no_history"
    return {"unusual": "deviating", "watch": "watch", "normal": "normal"}[evd["flag"]]


def _slim(e: dict) -> dict:
    return {k: v for k, v in e.items() if k != "history"}


def _splits(node: Node, sub: pd.DataFrame, m, bm, k: float, delta: float, flat: bool, compare_key: str) -> list[dict]:
    out = []
    sgn = 1.0 if delta >= 0 else -1.0
    for dim in node.split_dims:
        if not has_dim(sub, dim):
            continue
        lg = long(sub, dim, {"Q": (node.col, None)})
        cur, b = align(at(lg, m), at(lg, bm))
        dq = cur["Q"] - b["Q"]
        impact = k * dq
        fr = pd.DataFrame({"dq": dq, "impact": impact, "cur": cur["Q"], "base": b["Q"]})
        fr = fr[(fr["impact"].abs() > 0) | (fr["cur"] > 0)]
        if len(fr) < 2:
            continue
        aligned = fr["impact"] * sgn
        top1 = float(aligned.max())
        top1_share = None if flat else top1 / abs(delta) * 100
        wide = lg.pivot(index="m", columns="seg", values="Q").sort_index()
        order = fr["impact"].abs().sort_values(ascending=False).index[:RCA_TOP_N]
        shown = fr.loc[order].assign(_k=lambda d: d["impact"] * sgn).sort_values("_k", ascending=False)
        rows = []
        for seg, r in shown.iterrows():
            q, basis = ev.quantity("sum", wide[seg], compare_key)
            e = ev.verdict(q, m, basis, with_history=False)
            share = None if flat else r["impact"] / delta * 100
            rows.append({"segment": seg, "impact": num(r["impact"]), "share_pct": num(share),
                         "current": num(r["cur"]), "base": num(r["base"]), "change": num(r["dq"]),
                         "evidence": _slim(e), "flag": _flag(share, e)})
        rest = fr.drop(index=order)
        out.append({
            "key": dim, "label": DIMS[dim].label, "segments": int(len(fr)), "rows": rows,
            "other": ({"label": f"All other ({len(rest)})", "impact": num(rest["impact"].sum())} if len(rest) else None),
            "top_segment": aligned.idxmax() if top1 > 0 else None,
            "top1_share_pct": num(top1_share), "pattern": pattern_of(top1_share),
        })
    out.sort(key=lambda s: -(s["top1_share_pct"] or 0))
    return out


def _eval(node: Node, sc: Scope, frames: dict, T: dict, m, bm, delta: float, flat: bool, compare_key: str, measure) -> dict:
    d = {"id": node.id, "label": node.label, "how": node.how, "children": [], "splits": []}
    if node.fixed_impact is not None:
        impact = node.fixed_impact(T)
        share = None if flat else impact / delta * 100
        d.update(kind="effect", fmt=None, current=None, base=None, change=None, impact=num(impact),
                 share_pct=num(share), evidence={"available": False, "reason": "A calendar effect, not a quantity."},
                 flag="minor" if share is None or abs(share) < RCA_MATERIAL_SHARE_PCT else "normal")
        return d
    df = frames[node.table]
    sub = df if node.mask is None else df[node.mask(df).to_numpy(dtype=bool)]
    lg = long(sub, None, {"Q": (node.col, None)})
    cur, base_q = total(lg, m, "Q"), total(lg, bm, "Q")
    k = node.k(T)
    impact = k * (cur - base_q)
    share = None if flat else impact / delta * 100
    series = lg.set_index("m")["Q"].sort_index() if len(lg) else pd.Series(dtype=float)
    q, basis = ev.quantity("sum", series, compare_key)
    e = ev.verdict(q, m, basis, with_history=False)
    d.update(kind="quantity", fmt="currency", current=num(cur), base=num(base_q), change=num(cur - base_q),
             impact=num(impact), share_pct=num(share), evidence=_slim(e), flag=_flag(share, e))
    d["splits"] = _splits(node, sub, m, bm, k, delta, flat, compare_key) if node.split_dims else []
    d["children"] = [_eval(c, sc, frames, T, m, bm, delta, flat, compare_key, measure) for c in node.children]
    return d


def _lc(label: str) -> str:
    """Lower-case only the first letter so acronyms such as (OP) survive in sentences."""
    return label[:1].lower() + label[1:]


def walk(store, f: Filters, metric_key: str, month: str, compare_key: str) -> dict:
    if metric_key not in TREE_METRICS:
        raise RcaError(f"No KPI tree is defined for '{metric_key}'. Available: "
                       + ", ".join(MEASURES[k].label for k in TREE_METRICS) + ".")
    if compare_key not in TREE_COMPARES:
        raise RcaError("The KPI tree compares a month with the prior month or the same month last year.")
    measure = get_measure(metric_key)
    months = months_available(store)
    m = parse_month(month, months)
    base = make_base(measure, compare_key, m, months)
    bm = base.month
    sc = Scope(store, f, [])
    cur = measure.root_value(sc, m)
    base_val = measure.root_value(sc, bm)
    if cur is None or base_val is None:
        raise RcaError("No data for one of the two months in this scope.")
    delta = cur - base_val
    flat = is_flat(delta, base_val)
    T = _totals(metric_key, sc, m, bm)
    frames = {"cons": sc.cons_full, "inv": sc.inv_full.assign(_cls=stock_class(sc.inv_full))}
    root_def = _BUILDERS[metric_key]()
    children = [_eval(c, sc, frames, T, m, bm, delta, flat, compare_key, measure) for c in root_def.children]

    # truthfulness check: the branches must add up to the KPI's change
    branch_sum = sum(c["impact"] or 0.0 for c in children)
    gap = abs(branch_sum - delta)
    tol = 1e-6 * max(1.0, abs(delta), abs(cur))
    checks = [gap]
    for c in children:                         # and each branch's parts must add up to the branch
        if c["children"]:
            checks.append(abs(sum(x["impact"] or 0.0 for x in c["children"]) - (c["impact"] or 0.0)))
        for s in c["splits"]:                  # (only when every segment is shown)
            pass
    ok = max(checks) <= tol

    root = {"id": "root", "label": root_def.label, "how": root_def.how, "kind": "kpi", "fmt": measure.fmt,
            "current": num(cur), "base": num(base_val), "change": num(delta), "impact": num(delta),
            "share_pct": None if flat else 100.0,
            "evidence": {"available": False}, "flag": "minor", "splits": [], "children": children}

    # the chain: follow the largest branch at every level, then the top segment of its sharpest split
    chain = [{"id": "root", "label": root_def.label, "impact": num(delta), "share_pct": root["share_pct"], "flag": "minor"}]
    sgn = 1.0 if delta >= 0 else -1.0
    node = root
    while node["children"]:
        node = max(node["children"], key=lambda c: (c["impact"] or 0.0) * sgn)
        chain.append({"id": node["id"], "label": node["label"], "impact": node["impact"],
                      "share_pct": node["share_pct"], "flag": node["flag"]})
    if node["splits"]:
        sp = node["splits"][0]
        if sp["top_segment"]:
            r = next(x for x in sp["rows"] if x["segment"] == sp["top_segment"])
            chain.append({"id": f"{node['id']}:{sp['key']}", "label": f"{sp['label']}: {r['segment']}",
                          "impact": r["impact"], "share_pct": r["share_pct"], "flag": r["flag"]})

    out = {
        "metric": {"key": measure.key, "label": measure.label, "fmt": measure.fmt, "unit_word": measure.unit_word,
                   "higher_is": measure.higher_is, "definition": measure.definition},
        "period": {"month": m.strftime("%Y-%m"), "label": m.strftime("%b %Y")},
        "compare": {"key": base.key, "label": base.label},
        "scope": {"filters": f.as_dict()},
        "tree": root, "chain": chain, "flat": flat,
        "reconciliation": {"ok": bool(ok), "max_gap": num(max(checks)),
                           "checked": "Branches add up to the change in the KPI"},
        "thresholds": {"material_share_pct": RCA_MATERIAL_SHARE_PCT},
    }
    out["narrative"] = _narrate(measure, out)
    return out


def _narrate(measure, a: dict) -> list[str]:
    t, p, c = a["tree"], a["period"]["label"], a["compare"]["label"]
    delta = t["change"]
    if t["share_pct"] is None:
        return [f"{measure.label} was essentially flat versus {c} ({fmt_value(measure, t['base'])} to "
                f"{fmt_value(measure, t['current'])}), so shares of the change are not shown. Branch impacts below "
                f"may still be large and offset each other."]
    lines = [f"{measure.label} {'rose' if delta > 0 else 'fell'} {fmt_delta(measure, delta)} in {p} "
             f"({fmt_value(measure, t['base'])} in {c} to {fmt_value(measure, t['current'])})."]
    parts = []
    for b in sorted(t["children"], key=lambda x: -abs(x["impact"] or 0)):
        if b["impact"] is None or abs(b["impact"]) < RCA_NEGLIGIBLE_DELTA:
            continue
        parts.append(f"{_lc(b['label'])} {'added' if b['impact'] > 0 else 'took off'} "
                     f"{fmt_delta(measure, b['impact'])}")
    if parts:
        lines.append("The branches: " + "; ".join(parts) + ".")
    dev = []

    def collect(n):
        for ch in n["children"]:
            if ch["flag"] in ("deviating", "watch"):
                dev.append(ch)
            collect(ch)
    collect(t)
    flagged = [d for d in dev if d["flag"] == "deviating"]
    if flagged:
        lines.append("Branches that moved unusually against their own history: "
                     + ", ".join(_lc(d["label"]) for d in flagged) + ".")
    elif dev:
        lines.append("Branches worth watching: " + ", ".join(_lc(d["label"]) for d in dev) + ".")
    else:
        lines.append("No branch moved unusually against its own history.")
    return lines
