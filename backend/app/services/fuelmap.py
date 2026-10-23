"""Fuel-model maps from land cover, for the Rothermel spread simulation.

Sources
-------
recent   (default) ESA WorldCover 2021 v200 (10 m) gives the vegetation structure and non-burnable surfaces;
         MODIS MCD12Q1 v061 (500 m, latest year downloaded) types WorldCover tree pixels: leaf type from the
         plant-functional-type layer (LC_Type5), mixed forest from IGBP (LC_Type1).
ornl2005 / ornl1995 / ornl1985   ORNL Decadal LULC India (Roy et al. 2015, 100 m, UTM 44N): older, but with
         forest types mapped at 100 m. Useful for comparison and for historical fires.

Crosswalk to Anderson (1982) fuel models: a documented assumption for pre-monsoon (Feb–May) conditions,
not a field-calibrated fuel map.
- Deciduous broadleaf (sal, teak) and deciduous/low-elevation needleleaf (chir pine) forest → FM9 (litter fire)
- Evergreen needleleaf at or above 2700 m (fir, spruce, blue pine) → FM8 (compact litter)
- Evergreen broadleaf forest (e.g. banj oak, Western Ghats), plantations → FM8;  mixed forest → FM10
- Open woodland whose dominant plant type is grass or crop → FM2;  shrub-dominated woodland → FM6
- Shrubland → FM6;  cropland, fallow, wasteland → FM1 (stubble, dry grass)
- Grassland → FM3 below 3000 m, FM1 (short alpine grass) at or above 3000 m
- Water, built-up, bare/barren, snow & ice, wetlands, mangroves, moss/lichen, salt pan, aquaculture → NB
- No data (outside the source's coverage) → the user's selected fallback fuel model
"""
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("LANDCOVER_ROOT", r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\LandCover"))
ORNL_DIR = Path(os.environ.get("LANDCOVER_DIR", ROOT / "ORNL_India_LULC_1985_1995_2005"))
WC_DIR = ROOT / "ESA_WorldCover_2021_v200"
WC_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
MODIS_YEAR = int(os.environ.get("MODIS_LC_YEAR", "2025"))
MODIS_TIF = ROOT / f"MODIS_MCD12Q1_061_{MODIS_YEAR}" / f"MCD12Q1_{MODIS_YEAR}_IGBP_India_4326.tif"

NB = 0
NODATA = 127                      # ORNL no-data value
ALPINE_GRASS_M = 3000
SUBALPINE_CONIFER_M = 2700
SOURCES = {
    "recent": f"ESA WorldCover 2021 (10 m) + MODIS MCD12Q1 {MODIS_YEAR} forest types (500 m)",
    "ornl2005": "ORNL Decadal LULC India 2005 (100 m)",
    "ornl1995": "ORNL Decadal LULC India 1995 (100 m)",
    "ornl1985": "ORNL Decadal LULC India 1985 (100 m)",
}

# ---------------------------------------------------------------- legends: code -> (name, fuel, colour)
# fuel: model number, NB, None (= fallback), or "grass"/"conifer" (elevation-dependent rules)
ORNL = {
    1: ("Deciduous broadleaf forest", 9, "#c2a14a"), 2: ("Cropland", 1, "#f2e394"), 3: ("Built-up land", NB, "#9ca3af"),
    4: ("Mixed forest", 10, "#7c9a3a"), 5: ("Shrubland", 6, "#d59f5b"), 6: ("Barren land", NB, "#d6d3d1"),
    7: ("Fallow land", 1, "#efd9a7"), 8: ("Wasteland", 1, "#e3c89a"), 9: ("Water bodies", NB, "#3b82f6"),
    10: ("Plantations", 8, "#5fa35f"), 11: ("Aquaculture", NB, "#60a5fa"), 12: ("Mangrove forest", NB, "#0f766e"),
    13: ("Salt pan", NB, "#f5f5f4"), 14: ("Grassland", "grass", "#b7d36b"), 15: ("Evergreen broadleaf forest", 8, "#1f7a3a"),
    16: ("Deciduous needleleaf forest", 9, "#a3b86c"), 17: ("Permanent wetlands", NB, "#67e8f9"), 18: ("Snow & ice", NB, "#ffffff"),
    19: ("Evergreen needleleaf forest", "conifer", "#2f5d3a"), NODATA: ("No data (outside India)", None, "#6b7280"),
}
CLASSES = ORNL   # backwards-compatible name

# Combined "recent" legend: WorldCover codes; WorldCover tree cover (10) is typed from MODIS:
# leaf type from LC_Type5 (PFT), "mixed" from LC_Type1 (IGBP). IGBP alone is not used for leaf type because it
# labels open forests (e.g. Himalayan chir pine, 10-60 % cover) as (woody) savanna regardless of species.
RECENT = {
    20: ("Shrubland", 6, "#d59f5b"), 30: ("Grassland", "grass", "#b7d36b"), 40: ("Cropland", 1, "#f2e394"),
    50: ("Built-up", NB, "#9ca3af"), 60: ("Bare / sparse vegetation", NB, "#d6d3d1"), 70: ("Snow & ice", NB, "#ffffff"),
    80: ("Permanent water", NB, "#3b82f6"), 90: ("Herbaceous wetland", NB, "#67e8f9"), 95: ("Mangroves", NB, "#0f766e"),
    100: ("Moss & lichen", NB, "#c4b5fd"), 0: ("No data", None, "#6b7280"),
    1101: ("Tree cover: evergreen needleleaf", "conifer", "#2f5d3a"),
    1102: ("Tree cover: evergreen broadleaf", 8, "#1f7a3a"),
    1103: ("Tree cover: deciduous needleleaf", 9, "#a3b86c"),
    1104: ("Tree cover: deciduous broadleaf", 9, "#c2a14a"),
    1105: ("Tree cover: mixed forest", 10, "#7c9a3a"),
    1106: ("Tree cover: open woodland, grass understory", 2, "#cdbb5c"),
    1107: ("Tree cover: shrubby woodland", 6, "#b8894a"),
    1100: ("Tree cover: type unknown", 9, "#8a9a5b"),
}
PFT_TO_TREE = {1: 1101, 2: 1102, 3: 1103, 4: 1104, 5: 1107, 6: 1106, 7: 1106, 8: 1106}


def tree_codes(igbp: np.ndarray, pft: np.ndarray) -> np.ndarray:
    """Combined tree class from MODIS IGBP (band 1) and PFT (band 2)."""
    out = np.full(igbp.shape, 1100, np.int16)
    for p, code in PFT_TO_TREE.items():
        out[pft == p] = code
    out[igbp == 5] = 1105                          # IGBP mixed forest overrides the single dominant PFT
    return out


def fuel_for(fuel_rule, elev: np.ndarray, fallback: int) -> np.ndarray:
    if fuel_rule is None:
        return np.full(elev.shape, fallback, np.int16)
    if fuel_rule == "grass":
        return np.where(elev >= ALPINE_GRASS_M, 1, 3).astype(np.int16)
    if fuel_rule == "conifer":
        return np.where(elev >= SUBALPINE_CONIFER_M, 8, 9).astype(np.int16)
    return np.full(elev.shape, fuel_rule, np.int16)


def fuel_grid(classes: np.ndarray, elevation_m: np.ndarray, fallback_fuel: int, legend: dict = ORNL) -> np.ndarray:
    """Fuel-model number per cell (0 = non-burnable) from a class grid and its legend."""
    fuel = np.full(classes.shape, fallback_fuel, np.int16)          # unknown codes -> fallback
    for code, (_, rule, _) in legend.items():
        sel = classes == code
        if sel.any():
            fuel[sel] = fuel_for(rule, elevation_m[sel], fallback_fuel)
    return fuel


def fuel_label(rule) -> str:
    from .rothermel import FUEL_MODELS
    if rule is None:
        return "fallback fuel"
    if rule == NB:
        return "NB (non-burnable)"
    if rule == "grass":
        return "FM3 (<3000 m) / FM1 (≥3000 m)"
    if rule == "conifer":
        return "FM9 (<2700 m) / FM8 (≥2700 m)"
    return FUEL_MODELS[rule].code


def crosswalk_table(source: str = "recent") -> list[dict]:
    legend = RECENT if source == "recent" else ORNL
    return [{"class": k, "name": n, "fuel": fuel_label(r), "color": c} for k, (n, r, c) in sorted(legend.items())]


def available(source: str = "recent") -> bool:
    if source == "recent":
        return MODIS_TIF.exists()          # WorldCover falls back to the public COGs if tiles are not local
    return (ORNL_DIR / f"LULC_{source[-4:]}.tif").exists()


# ---------------------------------------------------------------- sampling
def _regular_bounds(lons: np.ndarray, lats: np.ndarray):
    """Grid must be regular in lon/lat (as built by firesim). Returns (west, south, east, north, shape)."""
    dlon = float(lons[0, 1] - lons[0, 0])
    dlat = float(lats[0, 0] - lats[1, 0])
    return (float(lons[0, 0] - dlon / 2), float(lats[-1, 0] - dlat / 2),
            float(lons[0, -1] + dlon / 2), float(lats[0, 0] + dlat / 2), lons.shape)


def _read_resampled(path_or_url, bounds, shape, resampling, nodata, band=1):
    import rasterio
    from rasterio.windows import from_bounds
    with rasterio.open(path_or_url) as ds:
        win = from_bounds(*bounds, transform=ds.transform)
        return ds.read(band, window=win, out_shape=shape, resampling=resampling, boundless=True, fill_value=nodata)


def _wc_tiles(bounds):
    w, s, e, n = bounds
    for lat in range(int(np.floor(s / 3) * 3), int(np.floor(n / 3) * 3) + 1, 3):
        for lon in range(int(np.floor(w / 3) * 3), int(np.floor(e / 3) * 3) + 1, 3):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            yield f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def sample_recent(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Combined class grid: WorldCover mode within each cell; tree cells refined by MODIS IGBP."""
    from rasterio.enums import Resampling
    bounds = _regular_bounds(lons, lats)
    *bb, shape = bounds
    wc = np.zeros(shape, np.uint8)
    for tile in _wc_tiles(bb):
        local = WC_DIR / f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
        src = local if local.exists() else WC_URL.format(tile=tile)
        try:
            part = _read_resampled(src, bb, shape, Resampling.mode, 0)
        except Exception:          # tile does not exist (open ocean) or network unavailable
            continue
        wc = np.where(wc == 0, part, wc)
    out = wc.astype(np.int16)
    trees = wc == 10
    if trees.any():
        if MODIS_TIF.exists():
            igbp = _read_resampled(MODIS_TIF, bb, shape, Resampling.nearest, 255, band=1)
            pft = _read_resampled(MODIS_TIF, bb, shape, Resampling.nearest, 255, band=2)
        else:
            igbp = pft = np.full(shape, 255, np.uint8)
        out[trees] = tree_codes(igbp[trees], pft[trees])
    return out


@lru_cache(maxsize=3)
def _ornl(year: int):
    import rasterio
    return rasterio.open(ORNL_DIR / f"LULC_{year}.tif")


def sample_ornl(lons: np.ndarray, lats: np.ndarray, year: int = 2005) -> np.ndarray:
    """Nearest-neighbour ORNL class at each lon/lat (UTM 44N raster)."""
    from pyproj import Transformer
    from rasterio.windows import Window, from_bounds
    ds = _ornl(year)
    x, y = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True).transform(lons, lats)
    out = np.full(lons.shape, NODATA, np.uint8)
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        return out
    pad = 2 * ds.res[0]
    try:
        win = from_bounds(x.min() - pad, y.min() - pad, x.max() + pad, y.max() + pad, ds.transform)
        win = win.round_offsets().round_lengths().intersection(Window(0, 0, ds.width, ds.height))
    except Exception:
        return out
    arr = ds.read(1, window=win)
    t = ds.window_transform(win)
    col = np.floor((x - t.c) / t.a).astype(int)
    row = np.floor((y - t.f) / t.e).astype(int)
    ok = (row >= 0) & (row < arr.shape[0]) & (col >= 0) & (col < arr.shape[1])
    out[ok] = arr[row[ok], col[ok]]
    return out


sample_classes = sample_ornl   # backwards-compatible name


def sample(source: str, lons: np.ndarray, lats: np.ndarray) -> tuple[np.ndarray, dict]:
    """Class grid and its legend for a land-cover source."""
    if source == "recent":
        return sample_recent(lons, lats), RECENT
    if not available(source):
        raise FileNotFoundError(f"{SOURCES[source]} is not available on this server")
    return sample_ornl(lons, lats, int(source[-4:])).astype(np.int16), ORNL
