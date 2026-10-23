import numpy as np
import pytest
from scipy import stats as sps

from app.services import climate as C

rng = np.random.default_rng(42)


def test_rh_vpd_saturation_and_known_value():
    rh, vpd = C.rh_vpd(np.array(25.0), np.array(25.0))
    assert rh == pytest.approx(100) and vpd == pytest.approx(0)
    assert C.es_kpa(np.array(20.0)) == pytest.approx(2.338, abs=0.002)   # FAO-56 table


def test_correlate_matches_scipy():
    x = rng.normal(size=60)
    y = 0.5 * x + rng.normal(size=60)
    y[[3, 10]] = np.nan
    ok = ~np.isnan(y)
    p = C.correlate(x, y, "pearson")
    s = C.correlate(x, y, "spearman")
    rp, pp = sps.pearsonr(x[ok], y[ok])
    rs, ps = sps.spearmanr(x[ok], y[ok])
    assert p["n"] == 58
    assert p["r"] == pytest.approx(rp) and p["p"] == pytest.approx(pp, rel=1e-6)
    assert s["r"] == pytest.approx(rs) and s["p"] == pytest.approx(ps, rel=1e-3)


def test_autocorrelation_reduces_effective_n():
    t = np.cumsum(rng.normal(size=200))       # random walks: strongly autocorrelated
    u = np.cumsum(rng.normal(size=200))
    c = C.correlate(t, u)
    assert c["n_eff"] < 0.2 * c["n"] and c["p_adj"] >= c["p"]


def test_deseasonalise_removes_monthly_means():
    months = np.tile(np.arange(1, 13), 5)
    v = months * 10.0 + rng.normal(size=60)
    d = C.deseasonalise(v, months)
    for m in range(1, 13):
        assert np.nanmean(d[months == m]) == pytest.approx(0, abs=1e-9)


def test_detrend():
    v = 3 + 2 * np.arange(20.0)
    assert np.allclose(C.detrend(v), 0)


def test_ols_recovers_coefficients_and_vif():
    n = 500
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    y = 1 + 2 * x1 - 3 * x2 + rng.normal(scale=0.1, size=n)
    r = C.ols(y, [x1, x2], ["x1", "x2"])
    b = {c["name"]: c["b"] for c in r["coef"]}
    assert b["intercept"] == pytest.approx(1, abs=0.02) and b["x1"] == pytest.approx(2, abs=0.02) and b["x2"] == pytest.approx(-3, abs=0.02)
    assert r["r2"] > 0.99 and all(c["vif"] < 1.1 for c in r["coef"][1:])
    assert 1.7 < r["durbin_watson"] < 2.3


def test_bh_fdr():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, np.nan])
    assert C.bh_fdr(p).tolist() == [True, True, False, False, False, False, False, False, False]
