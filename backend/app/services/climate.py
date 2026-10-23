"""Climate–fire statistics (reference implementation; the browser mirrors these in js/climstats.js).

All functions take aligned 1-D arrays and drop pairs with missing values.
"""
import math

import numpy as np
from scipy import stats as sps


def es_kpa(t_c):
    """Saturation vapour pressure (kPa), Tetens/FAO-56."""
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def rh_vpd(t_c, td_c):
    es, ea = es_kpa(t_c), es_kpa(td_c)
    return 100 * ea / es, es - ea


def deseasonalise(values, months, standardise=False):
    """Subtract each calendar month's mean (optionally divide by its SD)."""
    v = np.asarray(values, float).copy()
    m = np.asarray(months)
    for k in range(1, 13):
        sel = m == k
        if not sel.any():
            continue
        mu = np.nanmean(v[sel])
        v[sel] -= mu
        if standardise:
            sd = np.nanstd(v[sel], ddof=1)
            v[sel] = v[sel] / sd if sd > 0 else np.nan
    return v


def detrend(values):
    v = np.asarray(values, float)
    t = np.arange(len(v))
    ok = ~np.isnan(v)
    if ok.sum() < 3:
        return v
    b, a = np.polyfit(t[ok], v[ok], 1)
    return v - (a + b * t)


def lag1(v):
    v = v - v.mean()
    d = (v * v).sum()
    return float((v[1:] * v[:-1]).sum() / d) if d > 0 else 0.0


def correlate(x, y, method="pearson"):
    """r, two-sided p, n, and an autocorrelation-adjusted p (Bretherton et al. 1999 effective n)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 4 or x.std() == 0 or y.std() == 0:
        return {"r": None, "p": None, "n": n, "n_eff": None, "p_adj": None}
    if method == "spearman":
        x, y = sps.rankdata(x), sps.rankdata(y)
    r = float(np.corrcoef(x, y)[0, 1])
    p = t_pvalue(r, n)
    r1, r2 = lag1(x), lag1(y)
    n_eff = max(3.0, min(n, n * (1 - r1 * r2) / (1 + r1 * r2)))
    return {"r": r, "p": p, "n": n, "n_eff": n_eff, "p_adj": t_pvalue(r, n_eff)}


def t_pvalue(r, n):
    if abs(r) >= 1:
        return 0.0
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return float(2 * sps.t.sf(abs(t), n - 2))


def ols(y, X, names):
    """OLS with intercept. Returns coefficients, SE, t, p, R², adj R², Durbin–Watson, VIF."""
    y = np.asarray(y, float)
    X = np.column_stack([np.asarray(c, float) for c in X])
    ok = ~(np.isnan(y) | np.isnan(X).any(axis=1))
    y, X = y[ok], X[ok]
    n, k = X.shape
    if n <= k + 2:
        return {"n": n, "error": "too few observations"}
    A = np.column_stack([np.ones(n), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = n - k - 1
    s2 = resid @ resid / dof
    cov = s2 * np.linalg.inv(A.T @ A)
    se = np.sqrt(np.diag(cov))
    tv = beta / se
    p = 2 * sps.t.sf(np.abs(tv), dof)
    sst = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / sst
    vif = []
    for j in range(k):
        others = np.delete(X, j, axis=1)
        if others.shape[1] == 0:
            vif.append(1.0)
            continue
        Bo = np.column_stack([np.ones(n), others])
        fit = Bo @ np.linalg.lstsq(Bo, X[:, j], rcond=None)[0]
        r2j = 1 - ((X[:, j] - fit) ** 2).sum() / ((X[:, j] - X[:, j].mean()) ** 2).sum()
        vif.append(float(1 / (1 - r2j)) if r2j < 1 else math.inf)
    return {
        "n": n, "r2": float(r2), "adj_r2": float(1 - (1 - r2) * (n - 1) / dof),
        "durbin_watson": float((np.diff(resid) ** 2).sum() / (resid @ resid)),
        "coef": [{"name": nm, "b": float(b), "se": float(s), "t": float(t), "p": float(pp), "vif": v}
                 for nm, b, s, t, pp, v in zip(["intercept", *names], beta, se, tv, p, [None, *vif])],
    }


def bh_fdr(p, q=0.05):
    """Benjamini–Hochberg: boolean mask of discoveries (NaN p-values never significant)."""
    p = np.asarray(p, float)
    out = np.zeros(p.shape, bool)
    ok = np.where(~np.isnan(p))[0]
    if not len(ok):
        return out
    order = ok[np.argsort(p[ok])]
    m = len(order)
    thresh = q * np.arange(1, m + 1) / m
    passed = np.nonzero(p[order] <= thresh)[0]
    if len(passed):
        out[order[: passed[-1] + 1]] = True
    return out
