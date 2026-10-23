"""Aggregate ERA5-Land monthly + IMD daily data and MODIS fire detections to state × month, and
compute a 0.5° fire–climate correlation map.

Outputs:
  frontend/data/climate_state_monthly.json   per-region monthly series 2001-01 … 2025-12
  frontend/data/climate_corr_grid.json       0.5° Spearman maps (anomalies, fire-season months)

Usage: python scripts/build_climate.py   (needs build_history.py to have run first)
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DATA_DIR, HISTORY_PARQUET  # noqa: E402
from app.services.climate import bh_fdr, correlate, deseasonalise, rh_vpd  # noqa: E402

RAW = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data")
ERA5_FILES = [RAW / "ERA5/era5land_monthly/era5land_monthly_2000s.nc",
              RAW / "ERA5/era5land_monthly/era5land_monthly_2010s.nc",
              RAW / "ERA5/era5land_monthly/era5land_monthly_2020s.nc"]
IMD_DIR = Path(r"E:\Prem\Research_works\PhDFireResearch\02_Preprocessed\IMD")
STATES = RAW / "Boundaries/India_states_NWIC/state_NWIC.shp"
START, END = "2001-01-01", "2025-12-31"

VARS = {  # key: (label, unit, source, aggregation note)
    "imd_rain": ("Rainfall", "mm/month", "IMD 0.25° gridded (Pai et al. 2014)", "monthly total"),
    "imd_tmax": ("Max temperature", "°C", "IMD 1° gridded (Srivastava et al. 2009)", "monthly mean of daily Tmax"),
    "imd_tmin": ("Min temperature", "°C", "IMD 1° gridded", "monthly mean of daily Tmin"),
    "t2m": ("Air temperature (2 m)", "°C", "ERA5-Land monthly 0.1°", "monthly mean"),
    "rh": ("Relative humidity", "%", "ERA5-Land (from T2m, dew point)", "from monthly-mean T and Td"),
    "vpd": ("Vapour pressure deficit", "kPa", "ERA5-Land (from T2m, dew point)", "from monthly-mean T and Td"),
    "tp": ("Precipitation", "mm/month", "ERA5-Land monthly 0.1°", "monthly total"),
    "swvl1": ("Soil moisture 0–7 cm", "m³/m³", "ERA5-Land monthly 0.1°", "monthly mean"),
    "wind": ("Wind speed (10 m)", "m/s", "ERA5-Land monthly 0.1°", "speed of monthly-mean u,v (underestimates mean speed)"),
    "lai_hv": ("Leaf area index, high veg.", "m²/m²", "ERA5-Land monthly 0.1°", "monthly mean"),
}


def region_masks(lat, lon, states):
    """Dict region -> (mask over the 2-D grid, cos-lat weights). Cell centres inside the polygon."""
    lon2, lat2 = np.meshgrid(lon, lat)
    w = np.cos(np.radians(lat2))
    out = {}
    union = shapely.union_all(states.geometry.values)
    out["India"] = shapely.contains_xy(union, lon2, lat2)
    for name, geom in zip(states.state_name, states.geometry):
        out[name] = shapely.contains_xy(geom, lon2, lat2)
    return out, w


def regional_means(da, masks, w):
    """da: (time, lat, lon) -> {region: 1-D array}. NaN-aware cos-lat weighted mean."""
    arr = da.values
    res = {}
    for name, m in masks.items():
        if not m.any():
            res[name] = np.full(arr.shape[0], np.nan)
            continue
        sub = arr[:, m]
        ww = np.broadcast_to(w[m], sub.shape)
        ok = ~np.isnan(sub)
        num = np.where(ok, sub * ww, 0).sum(1)
        den = np.where(ok, ww, 0).sum(1)
        res[name] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    return res


def load_era5():
    keep = ["t2m", "d2m", "tp", "u10", "v10", "swvl1", "lai_hv"]
    parts = [xr.open_dataset(f)[keep].drop_vars(["number", "expver"], errors="ignore") for f in ERA5_FILES]
    ds = xr.concat(parts, dim="valid_time").rename({"valid_time": "time"}).sortby("time")
    ds = ds.sel(time=slice(START, END))
    days = ds.time.dt.days_in_month
    t = ds.t2m - 273.15
    td = ds.d2m - 273.15
    rh, vpd = rh_vpd(t, td)
    out = xr.Dataset({
        "t2m": t, "rh": rh, "vpd": vpd, "tp": ds.tp * 1000 * days, "swvl1": ds.swvl1,
        "wind": np.hypot(ds.u10, ds.v10), "lai_hv": ds.lai_hv,
    }).load()
    return out


def load_imd(var, how):
    da = xr.open_dataset(IMD_DIR / f"IMD_{var}_1951_2025.nc")[var].sel(time=slice(START, END))
    da = da.resample(time="MS").sum(min_count=20) if how == "sum" else da.resample(time="MS").mean()
    return da.load()


def main():
    states = gpd.read_file(STATES).to_crs(4326)[["state_name", "geometry"]]
    states["state_name"] = states["state_name"].str.strip()
    months = pd.date_range(START, END, freq="MS")

    fire = pd.read_parquet(HISTORY_PARQUET)
    fire["acq_date"] = pd.to_datetime(fire["acq_date"])
    fire = fire[(fire.acq_date >= START) & (fire.acq_date <= END)]
    fire["m"] = fire.acq_date.dt.to_period("M").dt.to_timestamp()

    def fire_series(df):
        g = df.groupby("m")
        return (g.size().reindex(months, fill_value=0).to_numpy(),
                g["frp"].mean().reindex(months).to_numpy())

    regions = {"India": fire_series(fire[fire.state.notna()])}
    for name, g in fire[fire.state.notna()].groupby("state"):
        regions[name] = fire_series(g)

    series = {r: {} for r in ["India", *states.state_name]}
    print("ERA5-Land …")
    era = load_era5()
    masks, w = region_masks(era.latitude.values, era.longitude.values, states)
    for v in ["t2m", "rh", "vpd", "tp", "swvl1", "wind", "lai_hv"]:
        for r, s in regional_means(era[v], masks, w).items():
            series[r][v] = s
    imd = {}
    for key, var, how in [("imd_rain", "rain", "sum"), ("imd_tmax", "tmax", "mean"), ("imd_tmin", "tmin", "mean")]:
        print("IMD", var, "…")
        da = load_imd(var, how)
        imd[key] = da
        m2, w2 = region_masks(da.lat.values, da.lon.values, states)
        for r, s in regional_means(da, m2, w2).items():
            series[r][key] = s

    r2 = lambda a: [None if (x is None or np.isnan(x)) else round(float(x), 3) for x in a]  # noqa: E731
    out = {
        "generated_utc": pd.Timestamp.now("UTC").isoformat(timespec="seconds"),
        "months": [m.strftime("%Y-%m") for m in months],
        "fire_product": "MODIS C6.1 Terra+Aqua active fire, type 0, FIRMS archive",
        "variables": {k: {"label": a, "unit": b, "source": c, "aggregation": d} for k, (a, b, c, d) in VARS.items()},
        "method": "Area means over grid cells whose centre lies in the region, weighted by cos(latitude). "
                  "Regions with no cell centre inside (small states on the IMD 1° temperature grid) are missing.",
        "regions": {},
    }
    for r in series:
        cnt, frp = regions.get(r, (np.zeros(len(months)), np.full(len(months), np.nan)))
        out["regions"][r] = {"fire_count": [int(x) for x in cnt], "fire_frp_mean": r2(frp),
                             **{k: r2(series[r][k]) for k in VARS}}
    (DATA_DIR / "climate_state_monthly.json").write_text(json.dumps(out, separators=(",", ":")))

    print("correlation maps …")
    build_corr_grid(fire, era, imd["imd_rain"], months)
    print("done")


def build_corr_grid(fire, era, imd_rain, months, cell=0.5, season=(2, 3, 4, 5)):
    """Spearman r between deseasonalised monthly fire counts and climate anomalies per 0.5° cell,
    using fire-season months only (Feb–May) and cells with >= 10 fire months."""
    lat_edges = np.arange(6, 38 + cell, cell)
    lon_edges = np.arange(68, 98 + cell, cell)
    ny, nx = len(lat_edges) - 1, len(lon_edges) - 1
    t_idx = {m: i for i, m in enumerate(months)}
    counts = np.zeros((len(months), ny, nx))
    iy = np.clip(((fire.latitude - 6) // cell).astype(int), 0, ny - 1)
    ix = np.clip(((fire.longitude - 68) // cell).astype(int), 0, nx - 1)
    it = fire.m.map(t_idx).to_numpy()
    np.add.at(counts, (it, iy.to_numpy(), ix.to_numpy()), 1)

    def coarse(da, latn, lonn):
        """Mean of source cells whose centre falls in each target cell -> (time, ny, nx)."""
        arr = da.transpose("time", latn, lonn).values
        li = np.floor((da[latn].values - 6) / cell).astype(int)
        lj = np.floor((da[lonn].values - 68) / cell).astype(int)
        s = np.zeros((arr.shape[0], ny, nx))
        n = np.zeros((arr.shape[0], ny, nx))
        for a, y in enumerate(li):
            if not 0 <= y < ny:
                continue
            for b, x in enumerate(lj):
                if 0 <= x < nx:
                    v = arr[:, a, b]
                    ok = ~np.isnan(v)
                    s[ok, y, x] += v[ok]
                    n[ok, y, x] += 1
        return np.where(n > 0, s / np.where(n > 0, n, 1), np.nan)

    fields = {
        "vpd": coarse(era.vpd, "latitude", "longitude"),
        "t2m": coarse(era.t2m, "latitude", "longitude"),
        "swvl1": coarse(era.swvl1, "latitude", "longitude"),
        "rh": coarse(era.rh, "latitude", "longitude"),
        "imd_rain": coarse(imd_rain, "lat", "lon"),
    }
    mon = np.array([m.month for m in months])
    in_season = np.isin(mon, season)
    res = {"cell_deg": cell, "lat0": 6, "lon0": 68, "ny": ny, "nx": nx, "season_months": list(season),
           "method": "Spearman r of monthly anomalies (calendar-month mean removed), Feb–May 2001–2025; "
                     "cells with ≥10 months with fire; significance: Benjamini–Hochberg FDR q=0.05 on autocorrelation-adjusted p.",
           "maps": {}}
    for key, f in fields.items():
        arr = f
        cells, ps = [], []
        for j in range(ny):
            for i in range(nx):
                c = counts[:, j, i]
                if (c[in_season] > 0).sum() < 10:
                    continue
                x = arr[:, j, i]
                if np.isnan(x).all():
                    continue
                fa = deseasonalise(np.log1p(c), mon)[in_season]
                xa = deseasonalise(x, mon)[in_season]
                cr = correlate(xa, fa, "spearman")
                if cr["r"] is None:
                    continue
                cells.append([j, i, round(cr["r"], 3)])
                ps.append(cr["p_adj"])
        sig = bh_fdr(np.array(ps))
        res["maps"][key] = [[*c, int(s)] for c, s in zip(cells, sig)]
        print(f"  {key}: {len(cells)} cells, {sig.sum()} significant")
    (DATA_DIR / "climate_corr_grid.json").write_text(json.dumps(res, separators=(",", ":")))


if __name__ == "__main__":
    main()
