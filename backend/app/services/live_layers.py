"""Live context layers: GFS wind, GDACS disaster alerts, official wildfire incidents, GIBS layer times."""
import logging
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

from ..cache import cache
from ..config import HTTP_TIMEOUT
from ..http import UpstreamError, get_text

log = logging.getLogger("kpsterra.layers")

GFS_URL = ("https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_1p00.pl?dir=%2Fgfs.{d}%2F{h:02d}%2Fatmos"
           "&file=gfs.t{h:02d}z.pgrb2.1p00.f{f:03d}&var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on")
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
GDACS_GEOM = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
NIFC_URL = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/"
            "FeatureServer/0/query")
CWFIS_URL = ("https://cwfis.cfs.nrcan.gc.ca/geoserver/public/ows?service=WFS&version=2.0.0&request=GetFeature"
             "&typeName=public:activefires_current&outputFormat=application/json")
GIBS_CAPS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml"
GIBS_LAYERS = ["Himawari_AHI_Band13_Clean_Infrared", "GOES-East_ABI_GeoColor", "GOES-West_ABI_GeoColor",
               "OMPS_Aerosol_Index", "MODIS_Combined_MAIAC_L2G_AerosolOpticalDepth", "VIIRS_SNPP_CorrectedReflectance_TrueColor"]


def _cached(key, ttl, fn):
    hit = cache.get(key, ttl)
    if hit is not None:
        return hit
    try:
        val = fn()
    except Exception as e:
        stale = cache.get_stale(key)
        if stale:
            log.warning("%s failed (%s); serving cached copy", key, e)
            return {**stale[1], "stale": True}
        raise UpstreamError(str(e)) from e
    cache.set(key, val)
    return val


# ---------- wind ----------
_DECODE = r"""
import sys, numpy as np, xarray as xr
ds = xr.open_dataset(sys.argv[1], engine="cfgrib", backend_kwargs={"indexpath": ""}).load()
np.savez(sys.argv[2], u=ds.u10.values, v=ds.v10.values, lat=ds.latitude.values, lon=ds.longitude.values,
         time=str(np.datetime_as_string(ds.time.values, unit="m")), valid=str(np.datetime_as_string(ds.valid_time.values, unit="m")))
"""


def decode_wind(grib_bytes: bytes) -> dict:
    # eccodes cannot load its definitions inside FastAPI worker threads (and can abort the process),
    # so decoding runs in a separate short-lived Python process.
    with tempfile.TemporaryDirectory() as tmp:
        p, out = os.path.join(tmp, "w.grb2"), os.path.join(tmp, "w.npz")
        with open(p, "wb") as f:
            f.write(grib_bytes)
        r = subprocess.run([sys.executable, "-c", _DECODE, p, out], capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(out):
            raise UpstreamError(f"GRIB decode failed: {r.stderr.strip()[-200:]}")
        with np.load(out) as z:   # close before the temp dir is removed (Windows file locks)
            u, v, lat, lon = z["u"].copy(), z["v"].copy(), z["lat"].copy(), z["lon"].copy()
            ref, valid = str(z["time"]), str(z["valid"])
    return _wind_payload(u, v, lat, lon, ref, valid)


def _wind_payload(u, v, lat, lon, ref, valid) -> dict:
    """u, v: (lat 90..-90, lon 0..359)."""
    return {
        "ref_time_utc": ref + "Z", "valid_time_utc": valid + "Z",
        "lat0": float(lat[0]), "lon0": float(lon[0]), "dlat": float(lat[1] - lat[0]), "dlon": float(lon[1] - lon[0]),
        "ny": int(u.shape[0]), "nx": int(u.shape[1]),
        # tenths of m/s as ints keeps the payload small
        "u": np.round(u * 10).astype(int).ravel().tolist(), "v": np.round(v * 10).astype(int).ravel().tolist(),
        "scale": 0.1,
    }


def wind(now: datetime | None = None) -> dict:
    def fetch():
        t = (now or datetime.now(timezone.utc)) - timedelta(hours=4)   # GFS cycles appear ~4 h after nominal time
        for back in range(4):
            c = t - timedelta(hours=6 * back)
            h = c.hour // 6 * 6
            fhr = 0
            r = httpx.get(GFS_URL.format(d=c.strftime("%Y%m%d"), h=h, f=fhr), timeout=HTTP_TIMEOUT)
            if r.status_code == 200 and r.content[:4] == b"GRIB":
                out = decode_wind(r.content)
                out.update(source="NOAA GFS 1° analysis (NOMADS)", retrieved_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                return out
        raise UpstreamError("no recent GFS cycle available")
    return _cached("wind", 3600, fetch)


# ---------- GDACS ----------
def gdacs() -> dict:
    def fetch():
        j = httpx.get(GDACS_URL, timeout=20).json()   # GDACS can be slow; fail fast and serve the cache
        feats, cyclones = [], []
        for f in j.get("features", []):
            p = f["properties"]
            feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
                "type": p.get("eventtype"), "name": p.get("name"), "alert": p.get("alertlevel"),
                "from": p.get("fromdate"), "to": p.get("todate"), "country": p.get("country"),
                "url": (p.get("url") or {}).get("report") if isinstance(p.get("url"), dict) else p.get("url"),
                "severity": (p.get("severitydata") or {}).get("severitytext")}})
            if p.get("eventtype") == "TC":
                cyclones.append(p)

        def track(p):
            try:
                g = httpx.get(GDACS_GEOM, params={"eventtype": "TC", "eventid": p["eventid"], "episodeid": p["episodeid"]},
                              timeout=20).json()
                return [{"type": "Feature", "geometry": gf["geometry"], "properties": {"name": p.get("name"), "alert": p.get("alertlevel")}}
                        for gf in g.get("features", []) if gf["geometry"]["type"] in ("LineString", "MultiLineString")]
            except Exception as e:
                log.warning("GDACS track %s: %s", p.get("eventid"), e)
                return []

        with ThreadPoolExecutor(max_workers=6) as pool:
            tracks = [t for ts in pool.map(track, cyclones) for t in ts]
        return {"source": "GDACS (UN/EC JRC)", "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "events": {"type": "FeatureCollection", "features": feats},
                "tc_tracks": {"type": "FeatureCollection", "features": tracks}}
    return _cached("gdacs", 900, fetch)


# ---------- official incidents ----------
def nifc_status(p: dict) -> str:
    """Map WFIGS fields to the legend's official categories. Never inferred from satellite data."""
    if p.get("IncidentTypeCategory") == "RX":
        return "prescribed"
    if p.get("FireOutDateTime"):
        return "out"
    if p.get("ControlDateTime") or p.get("ContainmentDateTime") or (p.get("PercentContained") or 0) >= 100:
        return "held"
    return "uncontained"


def us_incidents() -> dict:
    def fetch():
        fields = "IncidentName,IncidentSize,PercentContained,FireDiscoveryDateTime,ModifiedOnDateTime_dt,IncidentTypeCategory," \
                 "ContainmentDateTime,ControlDateTime,FireOutDateTime"
        j = httpx.get(NIFC_URL, params={"where": "IncidentTypeCategory IN ('WF','RX')", "outFields": fields, "f": "geojson"},
                      timeout=HTTP_TIMEOUT).json()
        feats = []
        for f in j.get("features", []):
            p = f["properties"]
            if not f.get("geometry"):
                continue
            ms = lambda k: datetime.fromtimestamp(p[k] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M") if p.get(k) else None  # noqa: E731
            feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
                "name": p.get("IncidentName"), "status": nifc_status(p), "acres": p.get("IncidentSize"),
                "contained_pct": p.get("PercentContained"), "discovered": ms("FireDiscoveryDateTime"), "updated": ms("ModifiedOnDateTime_dt")}})
        return {"source": "NIFC WFIGS current incidents (USA)", "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "geojson": {"type": "FeatureCollection", "features": feats}}
    return _cached("inc_us", 900, fetch)


CWFIS_STAGE = {"OC": "uncontained", "BH": "held", "UC": "held", "OUT": "out", "EX": "out", "PB": "prescribed"}


def canada_incidents() -> dict:
    def fetch():
        j = httpx.get(CWFIS_URL, timeout=HTTP_TIMEOUT).json()
        feats = [{"type": "Feature", "geometry": f["geometry"], "properties": {
            "name": f["properties"].get("firename"), "status": CWFIS_STAGE.get(str(f["properties"].get("stage_of_control", "")).upper(), "uncontained"),
            "hectares": f["properties"].get("hectares"), "agency": f["properties"].get("agency"), "updated": f["properties"].get("lastupdate")}}
            for f in j.get("features", []) if f.get("geometry")]
        return {"source": "CWFIS active fires (Canada)", "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "geojson": {"type": "FeatureCollection", "features": feats}}
    return _cached("inc_ca", 900, fetch)


# ---------- GIBS ----------
def gibs_times() -> dict:
    def fetch():
        x = get_text(GIBS_CAPS, label="GIBS capabilities")
        out = {}
        for lid in GIBS_LAYERS:
            i = x.find(f"<ows:Identifier>{lid}</ows:Identifier>")
            if i < 0:
                continue
            blk = x[i:x.find("</Layer>", i)]
            d = re.search(r"<Default>([^<]+)", blk)
            tms = re.search(r"<TileMatrixSet>([^<]+)", blk)
            out[lid] = {"time": d.group(1) if d else "default", "matrix": tms.group(1) if tms else None}
        return {"layers": out, "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return _cached("gibs", 600, fetch)
