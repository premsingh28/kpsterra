"""Satellite orbital elements and SGP4 propagation.

Elements come from CelesTrak, falling back to SatNOGS DB (which republishes Space-Track.org elements) and then
the TLE API mirror of CelesTrak (tle.ivanstanojevic.me).
They are cached on disk so server restarts do not re-download them (CelesTrak blocks clients that poll
too often), and the last good set is used, with its age shown, when every source is unavailable.
Positions are *estimates* from published two-line elements, not telemetry.
"""
import json
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sgp4.api import Satrec, jday

from ..config import CELESTRAK_BASE, ROOT, SATELLITES, TLE_CACHE_SECONDS

log = logging.getLogger("kpsterra.orbits")
EARTH_RADIUS_KM = 6378.137
WGS84_F = 1 / 298.257223563
SATNOGS = "https://db.satnogs.org/api/tle/"
TLE_API = "https://tle.ivanstanojevic.me/api/tle"
TLE_FILE = ROOT / "backend" / "cache" / "tle_cache.json"
SOURCE_TIMEOUT = 10.0
_lock = threading.Lock()
_down_until: dict[str, float] = {}          # source -> time before which we don't retry it


def _valid(l1: str, l2: str) -> bool:
    return l1.startswith("1 ") and l2.startswith("2 ") and len(l1) >= 69 and len(l2) >= 69


def _from_celestrak(norad: int):
    r = httpx.get(CELESTRAK_BASE, params={"CATNR": norad, "FORMAT": "tle"}, timeout=SOURCE_TIMEOUT)
    r.raise_for_status()
    lines = [ln.rstrip() for ln in r.text.strip().splitlines()]
    if len(lines) >= 3 and _valid(lines[1], lines[2]):
        return lines[0].strip(), lines[1], lines[2]
    raise ValueError(f"CelesTrak returned no TLE for {norad}")


def _from_satnogs(norad: int):
    r = httpx.get(SATNOGS, params={"norad_cat_id": norad, "format": "json"}, timeout=SOURCE_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    for t in r.json():
        if _valid(t["tle1"], t["tle2"]):
            return t["tle0"].removeprefix("0 ").strip(), t["tle1"], t["tle2"]
    raise ValueError(f"SatNOGS returned no TLE for {norad}")


def _from_tle_api(norad: int):
    r = httpx.get(f"{TLE_API}/{norad}", timeout=SOURCE_TIMEOUT, headers={"User-Agent": "KPSTerra/0.1 (research)"})
    r.raise_for_status()
    j = r.json()
    if _valid(j.get("line1", ""), j.get("line2", "")):
        return j["name"], j["line1"], j["line2"]
    raise ValueError(f"TLE API returned no TLE for {norad}")


SOURCES = [("CelesTrak", _from_celestrak), ("SatNOGS DB (Space-Track)", _from_satnogs),
           ("TLE API (CelesTrak mirror)", _from_tle_api)]


def _load() -> dict:
    try:
        return json.loads(TLE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    TLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TLE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(TLE_FILE)


def fetch_tle_record(norad: int) -> dict:
    """{'name','l1','l2','source','fetched'} — fresh if cached < TLE_CACHE_SECONDS, else refetched, else stale."""
    with _lock:
        data = _load()
        rec = data.get(str(norad))
        if rec and time.time() - rec["fetched"] < TLE_CACHE_SECONDS:
            return rec
        errors = []
        for name, fn in SOURCES:
            if _down_until.get(name, 0) > time.time():
                errors.append(f"{name}: skipped (failed recently)")
                continue
            try:
                n, l1, l2 = fn(norad)
                rec = {"name": n, "l1": l1, "l2": l2, "source": name, "fetched": time.time()}
                data[str(norad)] = rec
                _save(data)
                return rec
            except (httpx.HTTPError, ValueError, KeyError) as e:
                errors.append(f"{name}: {type(e).__name__}")
                if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)):
                    _down_until[name] = time.time() + 600     # don't hammer a source that is down
        if rec:
            log.warning("TLE %s: all sources failed (%s); using cached elements", norad, "; ".join(errors))
            return {**rec, "stale": True}
        raise RuntimeError("no orbital elements available: " + "; ".join(errors))


def fetch_tle(norad: int) -> tuple[str, str, str]:
    r = fetch_tle_record(norad)
    return r["name"], r["l1"], r["l2"]


def tle_epoch(line1: str) -> datetime:
    yy = int(line1[18:20])
    doy = float(line1[20:32])
    year = 2000 + yy if yy < 57 else 1900 + yy
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)


def gmst(jd_ut1: float) -> float:
    """Greenwich mean sidereal time (rad), IAU-82, as used by Vallado."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    g = (67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3)
    return math.radians((g % 86400.0) / 240.0) % (2 * math.pi)


def teme_to_geodetic(r: tuple[float, float, float], jd_full: float) -> tuple[float, float, float]:
    """TEME position (km) -> geodetic lat, lon (deg) and altitude (km). Ignores polar motion (~tens of m)."""
    th = gmst(jd_full)
    x = r[0] * math.cos(th) + r[1] * math.sin(th)
    y = -r[0] * math.sin(th) + r[1] * math.cos(th)
    z = r[2]
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    e2 = WGS84_F * (2 - WGS84_F)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(6):
        n = EARTH_RADIUS_KM / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * n * math.sin(lat), p)
    n = EARTH_RADIUS_KM / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    # Pole-safe form of h = p/cos(lat) - N
    alt = p * math.cos(lat) + (z + e2 * n * math.sin(lat)) * math.sin(lat) - n
    return math.degrees(lat), (math.degrees(lon) + 540) % 360 - 180, alt


def propagate(line1: str, line2: str, when: datetime) -> dict:
    sat = Satrec.twoline2rv(line1, line2)
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute,
                  when.second + when.microsecond / 1e6)
    err, r, v = sat.sgp4(jd, fr)
    if err != 0:
        raise ValueError(f"SGP4 error code {err}")
    lat, lon, alt = teme_to_geodetic(r, jd + fr)
    return {"lat": lat, "lon": lon, "alt_km": alt, "speed_km_s": math.sqrt(sum(c * c for c in v))}


def satellite_info(norad: int, when: datetime | None = None) -> dict:
    when = when or datetime.now(timezone.utc)
    rec = fetch_tle_record(norad)
    name, l1, l2 = rec["name"], rec["l1"], rec["l2"]
    epoch = tle_epoch(l1)
    meta = SATELLITES[norad]
    return {
        "norad_id": norad,
        **meta,
        "catalog_name": name,
        "tle_source": rec["source"],
        "tle_stale": bool(rec.get("stale")),
        "tle": [l1, l2],
        "tle_epoch_utc": epoch.isoformat(timespec="seconds"),
        "tle_age_hours": round((when - epoch).total_seconds() / 3600, 1),
        "position": propagate(l1, l2, when),
        "computed_utc": when.isoformat(timespec="seconds"),
    }


def ground_track(norad: int, minutes: int = 100, step_s: int = 60, when: datetime | None = None) -> list[list[float]]:
    when = when or datetime.now(timezone.utc)
    _, l1, l2 = fetch_tle(norad)
    pts = []
    for s in range(-minutes * 60 // 2, minutes * 60 // 2 + 1, step_s):
        p = propagate(l1, l2, when + timedelta(seconds=s))
        pts.append([round(p["lon"], 4), round(p["lat"], 4)])
    return pts
