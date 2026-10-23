"""KPSTerra API.

Run:  python -m uvicorn app.main:app --reload --port 8000   (from firescope/backend)
Docs: http://localhost:8000/docs
"""
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ALLOWED_ORIGINS, FIRMS_MAP_KEY, FIRMS_SOURCES, ROOT, SATELLITES
from .http import UpstreamError
import httpx

from .services import firesim, firms, fuelmap, history, live_layers, orbits, rothermel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="KPSTerra API", version="0.1.0",
              description="KPSTerra (KPS + Earth) by Katroth Premsingh: Earth observation, climate, water and fire. "
                          "Fire module: active fires (NASA FIRMS), satellite orbit estimates (SGP4), live context layers, "
                          "historical fire statistics for India, and Rothermel fire-spread simulation.")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"   # always revalidate local frontend files
    return response


@app.get("/api/health")
def health():
    try:
        history.load()
        hist = True
    except history.HistoryUnavailable:
        hist = False
    return {"status": "ok", "firms_key_configured": bool(FIRMS_MAP_KEY), "history_loaded": hist,
            "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


@app.get("/api/fires/live")
def live_fires(
    source: str = Query("VIIRS_NOAA20_NRT", description=f"One of {list(FIRMS_SOURCES)}"),
    days: int = Query(1, ge=1, le=5),
    region: Literal["india", "world"] = "india",
):
    bbox = firms.INDIA_BBOX if region == "india" else (-180.0, -90.0, 180.0, 90.0)
    try:
        return firms.fetch_fires(source, days, bbox)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except firms.FirmsNotConfigured as e:
        raise HTTPException(503, str(e))
    except UpstreamError as e:
        raise HTTPException(502, f"FIRMS unavailable: {e}")


@app.get("/api/satellites")
def satellites():
    out, errors = [], []
    for norad in SATELLITES:
        try:
            out.append(orbits.satellite_info(norad))
        except Exception as e:  # one bad satellite must not hide the others
            errors.append({"norad_id": norad, "name": SATELLITES[norad]["name"], "error": str(e)})
    return {"satellites": out, "errors": errors,
            "sources": sorted({s["tle_source"] for s in out}),
            "note": "Positions are SGP4 estimates from public orbital elements (CelesTrak, or SatNOGS/Space-Track as fallback), not live telemetry."}


@app.get("/api/satellites/{norad}/track")
def satellite_track(norad: int, minutes: int = Query(100, ge=10, le=300)):
    if norad not in SATELLITES:
        raise HTTPException(404, "satellite not in catalogue")
    try:
        return {"norad_id": norad, "track": orbits.ground_track(norad, minutes)}
    except Exception as e:
        raise HTTPException(502, str(e))


def _layer(fn):
    try:
        return fn()
    except UpstreamError as e:
        raise HTTPException(502, f"source unavailable: {e}")


@app.get("/api/layers/wind")
def layer_wind():
    """Latest GFS 10 m wind (1° grid, tenths of m/s)."""
    return _layer(live_layers.wind)


@app.get("/api/layers/gdacs")
def layer_gdacs():
    """Current GDACS disaster alerts and tropical-cyclone tracks."""
    return _layer(live_layers.gdacs)


@app.get("/api/layers/incidents")
def layer_incidents(region: Literal["us", "canada"] = "us"):
    """Official wildfire incidents with agency-reported status."""
    return _layer(live_layers.us_incidents if region == "us" else live_layers.canada_incidents)


@app.get("/api/layers/gibs-times")
def layer_gibs_times():
    """Latest available time for each NASA GIBS imagery layer used by the map."""
    return _layer(live_layers.gibs_times)


class Moisture(BaseModel):
    one_h: float = Field(6, ge=1, le=60, alias="1h")
    ten_h: float = Field(8, ge=1, le=60, alias="10h")
    hundred_h: float = Field(10, ge=1, le=60, alias="100h")
    herb: float = Field(60, ge=30, le=300)
    woody: float = Field(90, ge=30, le=300)

    def as_dict(self):
        return {"1h": self.one_h, "10h": self.ten_h, "100h": self.hundred_h, "herb": self.herb, "woody": self.woody}


class SimRequest(BaseModel):
    lat: float = Field(..., ge=-60, le=70)
    lon: float = Field(..., ge=-180, le=180)
    fuel: int
    moisture: Moisture = Moisture()
    wind_20ft_kmh: float = Field(10, ge=0, le=120)
    wind_from_deg: float = Field(270, ge=0, le=360)
    hours: float = Field(6, gt=0, le=24)
    waf: float | None = Field(None, gt=0, le=1)
    canopy_cover_pct: float = Field(0, ge=0, le=100)
    canopy_height_m: float = Field(0, ge=0, le=80)
    fuel_mode: Literal["uniform", "landcover"] = "uniform"
    lc_source: Literal["recent", "ornl2005", "ornl1995", "ornl1985"] = "recent"


@app.get("/api/sim/fuel-crosswalk")
def sim_fuel_crosswalk(source: Literal["recent", "ornl2005", "ornl1995", "ornl1985"] = "recent"):
    """Land-cover class -> fuel model assignment used when fuel_mode = landcover."""
    return {"source": source, "label": fuelmap.SOURCES[source], "available": fuelmap.available(source),
            "sources": {k: {"label": v, "available": fuelmap.available(k)} for k, v in fuelmap.SOURCES.items()},
            "classes": fuelmap.crosswalk_table(source), "notes": fuelmap.__doc__.strip()}


@app.get("/api/sim/fuel-models")
def sim_fuel_models():
    return [{"id": k, "code": f.code, "name": f.name, "depth_m": round(f.depth * 0.3048, 2), "mx_dead_pct": f.mx_dead,
             "dynamic": f.dynamic, "india_hint": f.india_hint} for k, f in rothermel.FUEL_MODELS.items()]


@app.post("/api/sim/rothermel")
def sim_rothermel(req: SimRequest):
    """Rothermel surface-fire spread from a point ignition over real terrain (minimum travel time)."""
    if req.fuel not in rothermel.FUEL_MODELS:
        raise HTTPException(422, "unknown fuel model")
    try:
        out = firesim.simulate(req.lat, req.lon, req.fuel, req.moisture.as_dict(), req.wind_20ft_kmh, req.wind_from_deg,
                               hours=req.hours, waf=req.waf, canopy_cover_pct=req.canopy_cover_pct,
                               canopy_height_m=req.canopy_height_m, fuel_mode=req.fuel_mode, lc_source=req.lc_source)
    except FileNotFoundError as e:
        raise HTTPException(503, f"{e}. Choose the 'Recent' land-cover source.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"terrain data unavailable: {e}")
    return {k: v for k, v in out.items() if not k.startswith("_")}


class PolygonRequest(BaseModel):
    geometry: dict
    start: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    min_confidence: int = Field(0, ge=0, le=100)


@app.post("/api/stats/polygon")
def stats_polygon(req: PolygonRequest):
    try:
        return history.polygon_stats(req.geometry, req.start, req.end, req.min_confidence)
    except history.HistoryUnavailable as e:
        raise HTTPException(503, str(e))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise HTTPException(422, f"invalid polygon: {e}")


# Serve the static frontend from the same server for local use (mounted last so /api wins).
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
