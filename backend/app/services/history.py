"""Historical MODIS archive for India, queried by custom polygon."""
from functools import lru_cache

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from ..config import HISTORY_PARQUET
from . import stats

MAX_VERTICES = 2000


class HistoryUnavailable(Exception):
    pass


@lru_cache(maxsize=1)
def load() -> pd.DataFrame:
    if not HISTORY_PARQUET.exists():
        raise HistoryUnavailable("Run scripts/build_history.py first")
    df = pd.read_parquet(HISTORY_PARQUET)
    df["acq_date"] = pd.to_datetime(df["acq_date"])
    return df


def polygon_stats(geometry: dict, start: str | None, end: str | None, min_conf: int = 0) -> dict:
    geom = shape(geometry)
    if geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid:
        raise ValueError("geometry must be a valid Polygon/MultiPolygon")
    if shapely.get_num_coordinates(geom) > MAX_VERTICES:
        raise ValueError("polygon too complex")
    df = load()
    minx, miny, maxx, maxy = geom.bounds
    sub = df[(df.longitude >= minx) & (df.longitude <= maxx) & (df.latitude >= miny) & (df.latitude <= maxy)]
    if start:
        sub = sub[sub.acq_date >= pd.Timestamp(start)]
    if end:
        sub = sub[sub.acq_date <= pd.Timestamp(end)]
    if min_conf:
        sub = sub[sub.confidence >= min_conf]
    inside = shapely.contains_xy(geom, sub.longitude.to_numpy(), sub.latitude.to_numpy())
    sub = sub[inside]
    out = stats.summarise(sub)
    out["area_km2"] = round(_area_km2(geom), 1)
    return out


def _area_km2(geom) -> float:
    lat0 = np.radians(geom.centroid.y)
    return geom.area * (111.32 ** 2) * np.cos(lat0)   # small-polygon approximation
