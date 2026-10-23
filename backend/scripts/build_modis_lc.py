"""Mosaic MODIS MCD12Q1 v061 HDF4 tiles into one India GeoTIFF in EPSG:4326 (nearest neighbour).
Band 1 = LC_Type1 (IGBP), band 2 = LC_Type5 (plant functional types: dominant leaf type even in open canopies).

Usage: python scripts/build_modis_lc.py [--year 2025] [--dir LANDCOVER_ROOT]
Output: <dir>/MODIS_MCD12Q1_061_<year>/MCD12Q1_<year>_IGBP_India_4326.tif
"""
import argparse
import re
from pathlib import Path

import numpy as np
import rasterio
from pyhdf.SD import SD, SDC
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject

SINU = CRS.from_proj4("+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs")
DEFAULT = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\LandCover")
BOUNDS = (66.0, 5.5, 99.0, 39.0)        # India + margin (lon/lat)
RES = 1 / 240                            # ~463 m, the native MODIS pixel near the equator


def read_tile(path: Path, sds: str = "LC_Type1"):
    sd = SD(str(path), SDC.READ)
    arr = sd.select(sds).get()
    meta = sd.attributes()["StructMetadata.0"]
    ulx, uly = map(float, re.search(r"UpperLeftPointMtrs=\(([^,]+),([^)]+)\)", meta).groups())
    lrx, _ = map(float, re.search(r"LowerRightMtrs=\(([^,]+),([^)]+)\)", meta).groups())
    px = (lrx - ulx) / arr.shape[1]
    return arr, from_origin(ulx, uly, px, px)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--dir", type=Path, default=DEFAULT)
    a = ap.parse_args()
    d = a.dir / f"MODIS_MCD12Q1_061_{a.year}"
    files = sorted(d.glob(f"MCD12Q1.A{a.year}001.*.hdf"))
    if not files:
        raise SystemExit(f"no MCD12Q1 {a.year} tiles in {d}")
    w, s, e, n = BOUNDS
    width, height = round((e - w) / RES), round((n - s) / RES)
    dst_t = from_origin(w, n, RES, RES)
    bands = []
    for sds in ("LC_Type1", "LC_Type5"):
        out = np.full((height, width), 255, np.uint8)
        for f in files:
            arr, t = read_tile(f, sds)
            tmp = np.full_like(out, 255)
            reproject(arr, tmp, src_transform=t, src_crs=SINU, src_nodata=255, dst_transform=dst_t,
                      dst_crs="EPSG:4326", dst_nodata=255, resampling=Resampling.nearest)
            out = np.where(out == 255, tmp, out)
        bands.append(out)
        print("  mosaicked", sds, flush=True)
    dest = d / f"MCD12Q1_{a.year}_IGBP_India_4326.tif"
    with rasterio.open(dest, "w", driver="GTiff", height=height, width=width, count=2, dtype="uint8", crs="EPSG:4326",
                       transform=dst_t, nodata=255, compress="deflate", tiled=True) as ds:
        for i, b in enumerate(bands, 1):
            ds.write(b, i)
        ds.set_band_description(1, "LC_Type1 IGBP")
        ds.set_band_description(2, "LC_Type5 PFT")
        ds.update_tags(source=f"MODIS MCD12Q1 v061, {a.year}", tiles=",".join(f.name.split(".")[2] for f in files))
    for name, b in zip(("IGBP", "PFT"), bands):
        vals, cnt = np.unique(b, return_counts=True)
        print(name, dict(zip(vals.tolist(), cnt.tolist())))
    print("written", dest)


if __name__ == "__main__":
    main()
