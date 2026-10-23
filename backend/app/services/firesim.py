"""Spatial surface-fire spread from a point ignition over real terrain.

Method (FARSITE/FlamMap-style minimum travel time, simplified):
1. Elevation for a square around the ignition from AWS Open Data terrain tiles (Terrarium PNG, zoom 12, ~30 m).
2. Slope and aspect per grid cell (central differences).
3. Rothermel/Albini head spread rate, direction of maximum spread and fire ellipse per cell, with the cell's
   slope and the (uniform) wind, fuel model and moistures.
4. Fire arrival time = shortest travel time on a 16-neighbour grid graph (Dijkstra). Edge time uses the
   elliptical spread rate in the edge direction at both cells.
5. Isochrones (perimeters) and burned area at regular times.

Fuels: either one fuel model everywhere, or per cell from land cover via the crosswalk in fuelmap.py:
by default ESA WorldCover 2021 (10 m, majority class per cell) + MODIS MCD12Q1 forest types; optionally the
ORNL India LULC 1985/1995/2005. Water, built-up, bare, wetlands, snow etc. are non-burnable and act as barriers.

Assumptions: uniform moisture and weather, surface fire only (no crowning or spotting), constant wind,
no suppression. This is a teaching and research tool, not an operational forecast.
"""
import base64
import io
import math
from functools import lru_cache

import contourpy
import httpx
import numpy as np
from PIL import Image
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from ..config import HTTP_TIMEOUT
from . import fuelmap
from . import rothermel as R

TERRAIN = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEM_ZOOM = 12
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON_EQ = 111_320.0
# 16-neighbour stencil (Knight's moves reduce the grid's directional bias)
OFFSETS = [(dy, dx) for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2)
           if (dy, dx) != (0, 0) and math.gcd(abs(dy), abs(dx)) == 1]


# ---------------------------------------------------------------- terrain
@lru_cache(maxsize=256)
def _tile(z: int, x: int, y: int) -> np.ndarray:
    r = httpx.get(TERRAIN.format(z=z, x=x, y=y), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768      # metres


def _lonlat_to_pixel(lon, lat, z):
    n = 2 ** z * 256
    x = (lon + 180) / 360 * n
    lat_r = np.radians(lat)
    y = (1 - np.log(np.tan(lat_r) + 1 / np.cos(lat_r)) / math.pi) / 2 * n
    return x, y


def elevation(lon: np.ndarray, lat: np.ndarray, z: int = DEM_ZOOM) -> np.ndarray:
    """Bilinear elevation (m) at arbitrary lon/lat arrays from Terrarium tiles."""
    px, py = _lonlat_to_pixel(lon, lat, z)
    px, py = px - 0.5, py - 0.5
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    tx = sorted(set(np.unique(x0 // 256).tolist()) | set(np.unique((x0 + 1) // 256).tolist()))
    ty = sorted(set(np.unique(y0 // 256).tolist()) | set(np.unique((y0 + 1) // 256).tolist()))
    mosaic = np.vstack([np.hstack([_tile(z, tx_, ty_) for tx_ in tx]) for ty_ in ty])
    ox, oy = tx[0] * 256, ty[0] * 256
    def at(xx, yy):
        return mosaic[yy - oy, xx - ox]
    fx, fy = px - x0, py - y0
    return ((at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx) * (1 - fy)
            + (at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx) * fy)


# ---------------------------------------------------------------- simulation
def simulate(lat: float, lon: float, fuel: int, moisture_pct: dict, wind_20ft_kmh: float, wind_from_deg: float,
             hours: float = 6.0, half_extent_km: float | None = None, cell_m: float | None = None, waf: float | None = None,
             canopy_cover_pct: float = 0.0, canopy_height_m: float = 0.0, step_min: float | None = None,
             elevation_fn=None, fuel_mode: str = "uniform", lc_source: str = "recent", classes_fn=None) -> dict:
    use_lc = fuel_mode == "landcover"
    if classes_fn is not None:                      # test hook: classes in the ORNL legend
        legend = fuelmap.ORNL
        sample_lc = classes_fn
    else:
        legend = fuelmap.RECENT if lc_source == "recent" else fuelmap.ORNL
        sample_lc = lambda lo, la: fuelmap.sample(lc_source, lo, la)[0]  # noqa: E731
    if half_extent_km is None:
        # size the domain from a worst case (wind aligned with a 60 % upslope) for the fuels near the ignition
        candidates = {fuel}
        if use_lc:
            dx, dy = np.meshgrid(np.linspace(-0.015, 0.015, 31), np.linspace(0.015, -0.015, 31))
            near = sample_lc(lon + dx / math.cos(math.radians(lat)), lat + dy)   # ~3 km box around the ignition
            candidates = {int(f) for f in np.unique(fuelmap.fuel_grid(near, np.zeros(near.shape), fuel, legend)) if f > 0} or {fuel}
        reach_m = max(R.surface_fire(f, moisture_pct, wind_20ft_kmh, wind_from_deg, 60, wind_from_deg, waf=waf,
                                     canopy_cover_pct=canopy_cover_pct, canopy_height_m=canopy_height_m).get("ros_head_m_min", 0)
                      for f in candidates) * hours * 60 * 1.15
        half_extent_km = min(20.0, max(1.5, reach_m / 1000))
    if cell_m is None:
        cell_m = max(30.0, 2 * half_extent_km * 1000 / 200)        # ~200 x 200 cells, never finer than the DEM
    n = int(round(2 * half_extent_km * 1000 / cell_m)) | 1          # odd, so the ignition is the centre cell
    c = n // 2
    coords = (np.arange(n) - c) * cell_m
    xx, yy = np.meshgrid(coords, -coords)                           # row 0 = north
    m_per_lon = M_PER_DEG_LON_EQ * math.cos(math.radians(lat))
    lons = lon + xx / m_per_lon
    lats = lat + yy / M_PER_DEG_LAT
    z = (elevation_fn or elevation)(lons, lats)

    dz_dy_rows, dz_dx = np.gradient(z, cell_m)                      # rows increase southwards
    dz_dy = -dz_dy_rows
    slope = np.hypot(dz_dx, dz_dy)                                  # rise/run
    upslope = (np.degrees(np.arctan2(dz_dx, dz_dy)) + 360) % 360   # compass bearing of steepest ascent

    # --- fuel model per cell
    classes = sample_lc(lons, lats) if use_lc else None
    fuel_g = fuelmap.fuel_grid(classes, z, fuel, legend) if use_lc else np.full((n, n), fuel, np.int16)
    m = {k: moisture_pct[k] / 100.0 for k in ("1h", "10h", "100h", "herb", "woody")}
    user_waf = waf
    shelter = R.sheltered_waf(canopy_cover_pct / 100, canopy_height_m / 0.3048, 0.5)

    # per-fuel-model constants, looked up per cell (index = fuel-model number; 0 = non-burnable)
    size = max(int(fuel_g.max()), fuel) + 1
    K = {k: np.zeros(size) for k in ("r0", "beta", "br", "ir", "cc", "bb", "ee", "waf")}
    unburnable_models = []
    for f in np.unique(fuel_g):
        if f <= 0:
            continue
        base = R.rothermel_no_wind(R.FUEL_MODELS[int(f)], m)
        if not base["burnable"]:
            unburnable_models.append(R.FUEL_MODELS[int(f)].code)
            continue
        s = base["sigma"]
        K["r0"][f], K["beta"][f], K["br"][f], K["ir"][f] = base["r0"], base["beta"], base["beta_ratio"], base["ir"]
        K["cc"][f] = 7.47 * math.exp(-0.133 * s ** 0.55)
        K["bb"][f] = 0.02526 * s ** 0.54
        K["ee"][f] = 0.715 * math.exp(-3.59e-4 * s)
        K["waf"][f] = waf if waf is not None else shelter if shelter is not None else R.unsheltered_waf(R.FUEL_MODELS[int(f)].depth)
    C = {k: v[fuel_g] for k, v in K.items()}
    burn = C["r0"] > 0

    if not burn[c, c]:
        if use_lc and fuel_g[c, c] == fuelmap.NB:
            name = legend.get(int(classes[c, c]), ("unknown land cover",))[0]
            return {"burnable": False, "reason": f"The ignition point is on {name.lower()}, which is treated as non-burnable. Pick a vegetated point."}
        fm0 = R.FUEL_MODELS[int(fuel_g[c, c])]
        return {"burnable": False, "reason": f"{fm0.code} does not burn at these moistures (dead fuel ≥ moisture of extinction {fm0.mx_dead:.0f} %)"}

    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        mid = wind_20ft_kmh * R.KMH_TO_MPH * C["waf"] * R.MPH_TO_FT_MIN                     # ft/min per cell
        phi_w = np.where(burn & (mid > 0), C["cc"] * mid ** C["bb"] * C["br"] ** -C["ee"], 0.0)
        phi_s = np.where(burn, 5.275 * C["beta"] ** -0.3 * slope ** 2, 0.0)
        r0 = C["r0"]
        wind_to = math.radians((wind_from_deg + 180) % 360)
        vx = r0 * phi_w * math.sin(wind_to) + r0 * phi_s * np.sin(np.radians(upslope))
        vy = r0 * phi_w * math.cos(wind_to) + r0 * phi_s * np.cos(np.radians(upslope))
        add = np.hypot(vx, vy)
        dir_max = np.where(add > 1e-9, (np.degrees(np.arctan2(vx, vy)) + 360) % 360, 0.0)
        phi_e = np.where(burn, add / r0, 0.0)
        u_eff = np.where(phi_e > 0, (phi_e * C["br"] ** C["ee"] / C["cc"]) ** (1 / C["bb"]), 0.0)
        limit = 0.9 * C["ir"]
        limited = burn & (u_eff > limit)
        u_eff = np.where(limited, limit, u_eff)
        phi_e = np.where(limited, C["cc"] * u_eff ** C["bb"] * C["br"] ** -C["ee"], phi_e)
    head = np.where(burn, r0 * (1 + phi_e), 0.0) * R.FT_MIN_TO_M_MIN                     # m/min
    u_mph = u_eff / 88.0
    lwr = np.where(u_mph > 1e-7, np.minimum(8.0, 0.936 * np.exp(0.1147 * u_mph) + 0.461 * np.exp(-0.0692 * u_mph) - 0.397), 1.0)
    ecc = np.sqrt(np.maximum(lwr ** 2 - 1, 0)) / lwr

    # --- travel-time graph
    idx = np.arange(n * n).reshape(n, n)
    rows, cols, wts = [], [], []
    for dy, dx in OFFSETS:
        ys, ye = max(0, -dy), n - max(0, dy)
        xs, xe = max(0, -dx), n - max(0, dx)
        a = idx[ys:ye, xs:xe]
        b = idx[ys + dy:ye + dy, xs + dx:xe + dx]
        dist = cell_m * math.hypot(dx, dy)
        bearing = (math.degrees(math.atan2(dx, -dy)) + 360) % 360     # dy>0 is south
        def ros_dir(sl):
            psi = np.radians(bearing - dir_max[sl])
            return head[sl] * (1 - ecc[sl]) / (1 - ecc[sl] * np.cos(psi))
        ra = ros_dir((slice(ys, ye), slice(xs, xe)))
        rb = ros_dir((slice(ys + dy, ye + dy), slice(xs + dx, xe + dx)))
        ok = (ra > 0) & (rb > 0)                                    # no edges into or out of non-burnable cells
        t = 0.5 * dist * (1 / ra[ok] + 1 / rb[ok])                  # minutes
        rows.append(a[ok]); cols.append(b[ok]); wts.append(t)
    g = csr_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(n * n, n * n))
    arrival = dijkstra(g, directed=True, indices=idx[c, c]).reshape(n, n)    # minutes

    total = hours * 60
    step = step_min or (30 if hours <= 3 else 60 if hours <= 12 else 120)
    levels = [float(t) for t in np.arange(step, total + 1e-6, step)]
    gen = contourpy.contour_generator(z=np.where(np.isfinite(arrival), arrival, 1e9), x=lons, y=lats)
    perims = []
    for t in levels:
        lines = gen.lines(t)
        burned_cells = int((arrival <= t).sum())
        perims.append({"type": "Feature", "properties": {"minutes": float(t), "hours": round(t / 60, 2),
                       "area_ha": round(burned_cells * cell_m ** 2 / 1e4, 1)},
                       "geometry": {"type": "MultiLineString", "coordinates": [np.round(l, 6).tolist() for l in lines if len(l) > 1]}})
    edge_reached = bool(np.nanmin(np.r_[arrival[0], arrival[-1], arrival[:, 0], arrival[:, -1]]) <= total)

    # point fire behaviour at the ignition cell, with that cell's fuel (full SI report)
    ign_fuel = int(fuel_g[c, c])
    point = R.surface_fire(ign_fuel, moisture_pct, wind_20ft_kmh, wind_from_deg, float(slope[c, c] * 100),
                           float((upslope[c, c] + 180) % 360), waf=user_waf,
                           canopy_cover_pct=canopy_cover_pct, canopy_height_m=canopy_height_m)
    point = {k: v for k, v in point.items() if not k.startswith("_")}

    # land-cover / fuel summary: share of the domain and area burned by the end of the run, per class
    burned = arrival <= total
    cell_ha = cell_m ** 2 / 1e4
    if use_lc:
        summary = []
        for cls in np.unique(classes):
            sel = classes == cls
            name, _, color = legend.get(int(cls), (f"class {cls}", None, "#888"))
            f_here = np.unique(fuel_g[sel])
            summary.append({"class": int(cls), "name": name, "color": color,
                            "fuel": ", ".join("NB" if f == 0 else R.FUEL_MODELS[int(f)].code for f in f_here),
                            "domain_pct": round(100 * sel.mean(), 1), "burned_ha": round(float((burned & sel).sum() * cell_ha), 1)})
        summary.sort(key=lambda s: -s["domain_pct"])
    else:
        summary = None
    ign_class = legend.get(int(classes[c, c]), ("?",))[0] if use_lc else None

    return {
        "burnable": True,
        "ignition": {"lat": lat, "lon": lon, "elevation_m": round(float(z[c, c]), 1),
                     "slope_pct": round(float(slope[c, c] * 100), 1), "aspect_deg": round(float((upslope[c, c] + 180) % 360), 0),
                     "fuel": R.FUEL_MODELS[ign_fuel].code, "landcover": ign_class},
        "point": point,
        "inputs": {"fuel": fuel, "fuel_code": R.FUEL_MODELS[fuel].code, "fuel_mode": fuel_mode,
                   "lc_source": lc_source if use_lc else None,
                   "lc_source_label": fuelmap.SOURCES.get(lc_source) if use_lc else None, "moisture_pct": moisture_pct,
                   "wind_20ft_kmh": wind_20ft_kmh, "wind_from_deg": wind_from_deg,
                   "waf": round(float(C["waf"][c, c]), 3), "waf_mode": "user" if user_waf is not None else "canopy" if shelter is not None else "per fuel bed depth",
                   "midflame_kmh": round(float(mid[c, c]) / R.MPH_TO_FT_MIN / R.KMH_TO_MPH, 2),
                   "hours": hours, "cell_m": cell_m, "half_extent_km": half_extent_km},
        "landcover_summary": summary,
        "nonburnable_pct": round(100 * float((~burn).mean()), 1),
        "unburnable_fuel_models": unburnable_models,
        "fuel_png": _classes_png(classes, legend) if use_lc else None,
        "grid": {"n": n, "cell_m": cell_m, "elev_min": round(float(z.min())), "elev_max": round(float(z.max())),
                 "slope_mean_pct": round(float(slope.mean() * 100), 1), "wind_limited_cells": int(limited.sum())},
        "_fuel_grid": fuel_g,
        "perimeters": {"type": "FeatureCollection", "features": perims},
        "final_area_ha": perims[-1]["properties"]["area_ha"] if perims else 0,
        "_arrival_min": arrival, "_xy_m": (xx, yy),
        "reached_domain_edge": edge_reached,
        "arrival_png": _arrival_png(arrival, total),
        "bounds": [[float(lons[0, 0] - cell_m / 2 / m_per_lon), float(lats[0, 0] + cell_m / 2 / M_PER_DEG_LAT)],
                   [float(lons[0, -1] + cell_m / 2 / m_per_lon), float(lats[0, -1] + cell_m / 2 / M_PER_DEG_LAT)],
                   [float(lons[-1, -1] + cell_m / 2 / m_per_lon), float(lats[-1, -1] - cell_m / 2 / M_PER_DEG_LAT)],
                   [float(lons[-1, 0] - cell_m / 2 / m_per_lon), float(lats[-1, 0] - cell_m / 2 / M_PER_DEG_LAT)]],
        "method": __doc__.strip(),
    }


def _png(rgba: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(rgba.astype(np.uint8), "RGBA").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _classes_png(classes: np.ndarray, legend: dict) -> str:
    """Land-cover classes in their legend colours (for the fuel-map overlay)."""
    rgba = np.zeros(classes.shape + (4,), np.uint8)
    for cls in np.unique(classes):
        h = legend.get(int(cls), ("", None, "#888888"))[2].lstrip("#")
        rgba[classes == cls] = [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 200]
    return _png(rgba)


def _arrival_png(arrival: np.ndarray, total_min: float) -> str:
    """Arrival time coloured yellow (early) -> red -> dark purple (late); transparent beyond the run time."""
    t = np.clip(arrival / total_min, 0, 1)
    stops = np.array([[255, 245, 160], [255, 170, 60], [235, 70, 40], [160, 20, 70], [70, 10, 80]], float)
    pos = t * (len(stops) - 1)
    i = np.clip(pos.astype(int), 0, len(stops) - 2)
    f = (pos - i)[..., None]
    rgb = stops[i] * (1 - f) + stops[i + 1] * f
    alpha = np.where(np.isfinite(arrival) & (arrival <= total_min), 190, 0)
    return _png(np.dstack([rgb, alpha]))
