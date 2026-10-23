"""Tests for calculations and API endpoints. Network calls are mocked; run with `python -m pytest`."""
import math
from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.services import firms, orbits, stats

# ISS reference TLE from the sgp4 / Vallado test set.
L1 = "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927"
L2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"


def test_tle_epoch():
    e = orbits.tle_epoch(L1)
    assert (e.year, e.month, e.day) == (2008, 9, 20)


def test_propagate_at_epoch_is_physical():
    p = orbits.propagate(L1, L2, orbits.tle_epoch(L1))
    assert 300 < p["alt_km"] < 450            # ISS altitude band
    assert 7.5 < p["speed_km_s"] < 7.8        # LEO orbital speed
    assert abs(p["lat"]) <= 51.7              # bounded by inclination


def test_teme_to_geodetic_poles_and_equator():
    lat, _, alt = orbits.teme_to_geodetic((0.0, 0.0, 6356.752 + 100), 2451545.0)
    assert lat == pytest.approx(90, abs=1e-6) and alt == pytest.approx(100, abs=0.01)
    lat, _, alt = orbits.teme_to_geodetic((6378.137 + 500, 0.0, 0.0), 2451545.0)
    assert lat == pytest.approx(0, abs=1e-9) and alt == pytest.approx(500, abs=1e-6)


def test_mann_kendall_known_cases():
    up = stats.mann_kendall(list(range(20)))
    assert up["trend"] == "increasing" and up["sen_slope"] == pytest.approx(1.0)
    flat = stats.mann_kendall([5, 3, 5, 3, 5, 3, 5, 3])
    assert flat["trend"] == "no significant trend"
    assert stats.mann_kendall([1, 2])["trend"] == "insufficient data"


def test_summarise_counts_and_anomaly():
    dates = pd.to_datetime(["2001-03-01"] * 10 + ["2002-03-01"] * 20 + ["2003-12-31"] * 30)
    df = pd.DataFrame({"acq_date": dates, "frp": 10.0})
    s = stats.summarise(df, baseline=(2001, 2002))
    assert s["n"] == 60 and s["yearly_count"] == [10, 20, 30]
    assert s["baseline_mean"] == 15 and s["anomaly_pct"] == [-33.3, 33.3, 100.0]
    assert s["climatology_mean_per_month"][2] == pytest.approx(10.0)   # March: 30 detections / 3 yrs


@pytest.mark.parametrize("raw,cls", [("l", "low"), ("n", "nominal"), ("h", "high"),
                                     ("10", "low"), ("50", "nominal"), ("95", "high"), ("x", "unknown")])
def test_confidence_class(raw, cls):
    assert firms.confidence_class(raw) == cls


def test_parse_viirs_csv():
    csv = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,"
           "version,bright_ti5,frp,daynight\n13.1,79.3,341.2,0.5,0.4,2026-10-22,731,N20,VIIRS,n,2.0NRT,294.7,5.1,D\n")
    df = firms.parse_firms_csv(csv, "VIIRS_NOAA20_NRT")
    assert df.loc[0, "acq_datetime"] == pd.Timestamp("2026-10-22 07:31", tz="UTC")
    assert df.loc[0, "conf_class"] == "nominal"
    gj = firms.to_geojson(df)
    assert gj["features"][0]["geometry"]["coordinates"] == [79.3, 13.1]


client = TestClient(main.app)


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_live_fires_rejects_bad_input():
    assert client.get("/api/fires/live?days=9").status_code == 422
    assert client.get("/api/fires/live?source=FAKE").status_code == 422


def test_live_fires_without_key(monkeypatch):
    monkeypatch.setattr(firms, "FIRMS_MAP_KEY", "")
    r = client.get("/api/fires/live?source=MODIS_NRT&days=2")
    assert r.status_code == 503


def test_tle_falls_back_to_second_source_and_then_cache(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(orbits, "TLE_FILE", tmp_path / "tle.json")
    monkeypatch.setattr(orbits, "_down_until", {})
    def down(n):
        raise httpx.ConnectTimeout("celestrak down")
    calls = []
    def satnogs(n):
        calls.append(n)
        return ("TERRA", L1, L2)
    monkeypatch.setattr(orbits, "SOURCES", [("CelesTrak", down), ("SatNOGS", satnogs)])
    rec = orbits.fetch_tle_record(25994)
    assert rec["source"] == "SatNOGS" and not rec.get("stale")
    assert (tmp_path / "tle.json").exists()                       # persisted across restarts
    # cache is fresh: no new request
    orbits.fetch_tle_record(25994)
    assert calls == [25994]
    # everything down and cache expired -> stale cached copy, flagged
    monkeypatch.setattr(orbits, "TLE_CACHE_SECONDS", -1)
    monkeypatch.setattr(orbits, "SOURCES", [("CelesTrak", down), ("SatNOGS", down)])
    rec = orbits.fetch_tle_record(25994)
    assert rec["stale"] is True and rec["l1"] == L1


def test_satellites_endpoint_mocked(monkeypatch):
    monkeypatch.setattr(orbits, "fetch_tle_record", lambda n: {"name": "TEST", "l1": L1, "l2": L2, "source": "test", "fetched": 0})
    body = client.get("/api/satellites").json()
    assert len(body["satellites"]) == 9 and not body["errors"]
    assert "estimates" in body["note"]


def test_polygon_validation():
    r = client.post("/api/stats/polygon", json={"geometry": {"type": "Point", "coordinates": [0, 0]}})
    assert r.status_code in (422, 503)
    r = client.post("/api/stats/polygon", json={"geometry": {}, "start": "bad"})
    assert r.status_code == 422
