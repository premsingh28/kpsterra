"""NASA FIRMS near-real-time active-fire ingestion."""
import io
from datetime import datetime, timezone

import pandas as pd

from ..cache import cache
from ..config import FIRES_CACHE_SECONDS, FIRMS_BASE, FIRMS_MAP_KEY, FIRMS_SOURCES
from ..http import UpstreamError, get_text

INDIA_BBOX = (68.0, 6.0, 98.0, 38.0)


class FirmsNotConfigured(Exception):
    pass


def parse_firms_csv(text: str, source: str) -> pd.DataFrame:
    """Normalise MODIS and VIIRS CSVs to one schema."""
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return df
    df = df.rename(columns={"bright_ti4": "brightness", "bright_ti5": "bright_t31"})
    t = df["acq_time"].astype(int).astype(str).str.zfill(4)
    df["acq_datetime"] = pd.to_datetime(df["acq_date"] + " " + t, format="%Y-%m-%d %H%M", utc=True)
    df["source"] = source
    # VIIRS confidence is l/n/h; MODIS is 0-100. Keep both raw and a common class.
    df["confidence"] = df["confidence"].astype(str)
    df["conf_class"] = df["confidence"].map(confidence_class)
    return df


def confidence_class(value: str) -> str:
    v = str(value).strip().lower()
    if v in ("l", "low"):
        return "low"
    if v in ("n", "nominal"):
        return "nominal"
    if v in ("h", "high"):
        return "high"
    try:
        n = float(v)
    except ValueError:
        return "unknown"
    # MODIS C6.1 user guide classes: <30 low, 30-79 nominal, >=80 high
    return "low" if n < 30 else "nominal" if n < 80 else "high"


def fetch_fires(source: str, days: int, bbox: tuple[float, float, float, float]) -> dict:
    if source not in FIRMS_SOURCES:
        raise ValueError(f"unknown source {source}")
    if not FIRMS_MAP_KEY:
        raise FirmsNotConfigured("FIRMS_MAP_KEY is not set on the server")
    area = ",".join(f"{v:g}" for v in bbox)
    key = f"firms:{source}:{area}:{days}"
    hit = cache.get(key, FIRES_CACHE_SECONDS)
    if hit is not None:
        return hit
    url = f"{FIRMS_BASE}/{FIRMS_MAP_KEY}/{source}/{area}/{days}"
    try:
        text = get_text(url, label=f"FIRMS {source}")
    except UpstreamError:
        stale = cache.get_stale(key)
        if stale:
            return {**stale[1], "stale": True}
        raise
    if text.lstrip().lower().startswith(("invalid", "error")):
        raise UpstreamError(f"FIRMS replied: {text[:120]}")
    df = parse_firms_csv(text, source)
    result = {
        "source": source,
        "source_label": FIRMS_SOURCES[source],
        "bbox": bbox,
        "days": days,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": int(len(df)),
        "geojson": to_geojson(df),
        "stale": False,
    }
    cache.set(key, result)
    return result


def to_geojson(df: pd.DataFrame) -> dict:
    feats = []
    for r in df.itertuples(index=False):
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(r.longitude, 5), round(r.latitude, 5)]},
            "properties": {
                "t": r.acq_datetime.isoformat(),
                "sat": str(r.satellite),
                "inst": str(r.instrument),
                "frp": None if pd.isna(r.frp) else float(r.frp),
                "conf": str(r.confidence),
                "cc": r.conf_class,
                "bt": None if pd.isna(r.brightness) else float(r.brightness),
                "dn": str(r.daynight),
                "scan": float(r.scan),
                "track": float(r.track),
                "ver": str(r.version),
            },
        })
    return {"type": "FeatureCollection", "features": feats}
