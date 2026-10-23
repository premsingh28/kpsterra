"""Time-series statistics for fire detections. Pure functions, unit-tested."""
import math

import numpy as np
import pandas as pd
from scipy import stats as sps


def mann_kendall(y: list[float]) -> dict:
    """Mann-Kendall trend test (no tie/autocorrelation correction beyond ties in variance) + Sen's slope."""
    x = np.asarray(y, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 4:
        return {"n": n, "s": None, "z": None, "p": None, "sen_slope": None, "trend": "insufficient data"}
    s = 0
    for i in range(n - 1):
        s += np.sign(x[i + 1:] - x[i]).sum()
    _, counts = np.unique(x, return_counts=True)
    var_s = (n * (n - 1) * (2 * n + 5) - (counts * (counts - 1) * (2 * counts + 5)).sum()) / 18
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    p = 2 * (1 - sps.norm.cdf(abs(z)))
    return {
        "n": n, "s": int(s), "z": float(z), "p": float(p),
        "sen_slope": sen_slope(x),
        "trend": ("increasing" if z > 0 else "decreasing") if p < 0.05 else "no significant trend",
    }


def sen_slope(y) -> float:
    x = np.asarray(y, dtype=float)
    n = len(x)
    slopes = [(x[j] - x[i]) / (j - i) for i in range(n - 1) for j in range(i + 1, n)]
    return float(np.median(slopes))


def summarise(df: pd.DataFrame, baseline: tuple[int, int] = (2001, 2020)) -> dict:
    """df needs columns acq_date (datetime64), frp. Returns everything the stats panel draws."""
    if df.empty:
        return {"n": 0}
    d = df.copy()
    d["year"] = d["acq_date"].dt.year
    d["month"] = d["acq_date"].dt.month
    years = list(range(int(d["year"].min()), int(d["year"].max()) + 1))
    yearly = d.groupby("year").size().reindex(years, fill_value=0)
    frp_year = d.groupby("year")["frp"].sum().reindex(years, fill_value=0)
    monthly = d.groupby([d["acq_date"].dt.to_period("M")]).size()
    clim = d.groupby("month").size().reindex(range(1, 13), fill_value=0) / len(years)
    base = yearly[(yearly.index >= baseline[0]) & (yearly.index <= baseline[1])]
    base_mean = float(base.mean()) if len(base) else None
    hist, edges = np.histogram(np.log10(d["frp"].clip(lower=0.1)), bins=30)
    # Exclude an incomplete final year from the trend test.
    complete = yearly
    last = d["acq_date"].max()
    if not (last.month == 12 and last.day >= 28):
        complete = yearly.iloc[:-1]
    return {
        "n": int(len(d)),
        "first_date": d["acq_date"].min().strftime("%Y-%m-%d"),
        "last_date": last.strftime("%Y-%m-%d"),
        "years": years,
        "yearly_count": yearly.astype(int).tolist(),
        "yearly_frp_sum_mw": frp_year.round(1).tolist(),
        "monthly_index": [str(p) for p in monthly.index],
        "monthly_count": monthly.astype(int).tolist(),
        "climatology_mean_per_month": clim.round(1).tolist(),
        "baseline": list(baseline),
        "baseline_mean": base_mean,
        "anomaly_pct": [None if not base_mean else round(100 * (v - base_mean) / base_mean, 1) for v in yearly],
        "frp": {
            "mean": float(d["frp"].mean()), "median": float(d["frp"].median()),
            "p95": float(d["frp"].quantile(0.95)), "max": float(d["frp"].max()),
            "log10_hist": hist.astype(int).tolist(), "log10_edges": edges.round(3).tolist(),
        },
        "trend": {**mann_kendall(complete.tolist()), "years": [int(complete.index[0]), int(complete.index[-1])]},
    }
