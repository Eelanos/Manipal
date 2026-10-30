"""
Predictive Analysis (demand & replenishment planning).

Rule-based and fully explainable - no machine learning. Every number is
computed from the same Parquet data the dashboards use, through the same
filters, so it can be checked by hand:

    params.py   every setting, default, limit and constant (nothing hardcoded elsewhere)
    engine.py   the formulas: daily usage, days of cover, reorder point, order
                quantity, excess, expiry risk, seasonality, forecast + range
    ../routers/predict.py   GET /api/predict/{options,overview,item}

Additive and isolated: it only READS the DataStore. Existing dashboards, RCA and
chat do not import it and are unaffected.
"""
