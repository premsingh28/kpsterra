"""Precompute static historical data from the local FIRMS MODIS India archive.

Outputs (all small enough for GitHub Pages):
  frontend/data/states.geojson      simplified Survey-of-India state boundaries (via NWIC)
  frontend/data/state_stats.json    per-state + all-India summaries (counts, FRP, seasonality, trend)
  frontend/data/grid_yearly.json    0.25 deg cell counts per year (3D columns)
  backend/cache/modis_india.parquet compact archive for custom-polygon queries (not committed)

Usage: python scripts/build_history.py [--archive DIR] [--states SHP]
"""
import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DATA_DIR, HISTORY_PARQUET  # noqa: E402
from app.services.stats import summarise  # noqa: E402

DEFAULT_ARCHIVE = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\FIRMS\india_archive\modis")
DEFAULT_STATES = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\Boundaries\India_states_NWIC\state_NWIC.shp")
CELL = 0.25


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    ap.add_argument("--states", type=Path, default=DEFAULT_STATES)
    a = ap.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PARQUET.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(a.archive.glob("modis_*_India.csv"))
    cols = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "frp", "daynight", "type"]
    df = pd.concat((pd.read_csv(f, usecols=cols) for f in files), ignore_index=True)
    n_all = len(df)
    df = df[df["type"] == 0].drop(columns="type")   # 0 = presumed vegetation fire
    df["acq_date"] = pd.to_datetime(df["acq_date"])
    print(f"{len(files)} files, {n_all:,} detections, {len(df):,} type-0 (vegetation)")

    states = gpd.read_file(a.states).to_crs(4326)[["state_name", "geometry"]]
    states["state_name"] = states["state_name"].str.strip()
    pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=4326)
    joined = gpd.sjoin(pts, states, how="left", predicate="within")
    df["state"] = joined["state_name"].values
    print(f"assigned to a state: {df['state'].notna().mean():.1%}")

    df.to_parquet(HISTORY_PARQUET, index=False)

    out = {"product": "MODIS C6.1 active fire (Terra+Aqua), FIRMS archive, type=0",
           "generated_utc": pd.Timestamp.now("UTC").isoformat(timespec="seconds"),
           "india": summarise(df), "states": {}}
    india_only = df[df["state"].notna()]
    out["india_in_boundary"] = summarise(india_only)
    for name, g in india_only.groupby("state"):
        out["states"][name] = summarise(g)
    (DATA_DIR / "state_stats.json").write_text(json.dumps(out, separators=(",", ":")))

    simp = states.copy()
    simp["geometry"] = simp.geometry.simplify(0.01, preserve_topology=True)
    tot = india_only.groupby("state").size()
    simp["total"] = simp["state_name"].map(tot).fillna(0).astype(int)
    simp.to_file(DATA_DIR / "states.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)

    df["cx"] = (np.floor(df.longitude / CELL) * CELL).round(2)
    df["cy"] = (np.floor(df.latitude / CELL) * CELL).round(2)
    df["year"] = df.acq_date.dt.year
    years = list(range(int(df.year.min()), int(df.year.max()) + 1))
    piv = df.groupby(["cx", "cy", "year"]).size().unstack(fill_value=0).reindex(columns=years, fill_value=0)
    frp = df.groupby(["cx", "cy"])["frp"].mean()
    cells = [[cx, cy, round(float(frp[(cx, cy)]), 1), *map(int, row)] for (cx, cy), row in piv.iterrows()]
    (DATA_DIR / "grid_yearly.json").write_text(json.dumps(
        {"cell_deg": CELL, "years": years, "fields": ["lon", "lat", "mean_frp", *years], "cells": cells},
        separators=(",", ":")))
    print("done:", DATA_DIR)


if __name__ == "__main__":
    main()
