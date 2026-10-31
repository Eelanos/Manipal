"""
The dimensions a change can be split by.

One catalogue, used by the driver analysis and the KPI tree, so a dimension is
added in exactly one place. Each dimension names the dataframe column it reads.
Which dimensions a METRIC can use is decided in metrics.py: a metric can only
be split by a dimension that its underlying tables actually record (stock has
no doctor, for example), and the API says so instead of guessing.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Dim:
    key: str
    label: str
    col: str
    # For True/False columns: (label when False, label when True).
    bool_labels: tuple[str, str] | None = None


DIMS: dict[str, Dim] = {d.key: d for d in [
    # Region and Zone are columns on every fact table (the network hierarchy). Cluster is left out on
    # purpose: in this data every unit is its own cluster, so it would just repeat the unit.
    Dim("region", "Region", "Region"),
    Dim("zone", "Zone", "Zone"),
    Dim("unit", "Unit", "Unit_Name"),
    Dim("department", "Department", "Dept_Name"),
    Dim("item", "Item", "Item_Name"),
    Dim("doctor", "Doctor", "Doctor"),
    Dim("payer", "Payer type", "Payer_Type"),
    Dim("patient_type", "Patient type", "Patient_Type"),
    Dim("episode", "Episode type", "Episode_Type"),
    Dim("package", "Package status", "Is_Package", ("Non-package", "Package")),
    Dim("store", "Store", "Store_Location"),
    Dim("category", "Category", "Category"),
    Dim("tier", "Formulary tier", "Formulary_Tier"),
    Dim("stock_group", "Stock take group", "Stock Take Group"),
    Dim("implant", "Implant status", "Is_Implant", ("Non-implant", "Implant")),
    Dim("essential", "Essential status", "Is_Essential", ("Non-essential", "Essential")),
]}

BLANK = "(blank)"


def seg_series(df: pd.DataFrame, key: str) -> pd.Series:
    """The segment label of every row of df for dimension `key`, as plain strings."""
    d = DIMS[key]
    s = df[d.col]
    if d.bool_labels:
        s = s.map({False: d.bool_labels[0], True: d.bool_labels[1]})
    return s.astype(object).where(s.notna(), BLANK).astype(str)


def has_dim(df: pd.DataFrame, key: str) -> bool:
    return DIMS[key].col in df.columns
