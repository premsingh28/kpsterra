"""Download recent land cover for India (resumable; already-complete files are skipped).

1. ESA WorldCover 2021 v200, 10 m: 3x3 degree COG tiles intersecting India, from the public AWS bucket (no login).
2. MODIS MCD12Q1 v061 (IGBP land cover, 500 m), all India tiles for the latest available year, from NASA
   LP DAAC using the Earthdata login in EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or ~/.netrc).

Usage: python scripts/download_landcover.py [--out DIR] [--year 2025] [--only worldcover|modis]
"""
import argparse
import os
import sys
from pathlib import Path

import httpx

DEFAULT_OUT = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\LandCover")
WC_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
STATES = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\Boundaries\India_states_NWIC\state_NWIC.shp")
CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"


def india_tiles() -> list[str]:
    import geopandas as gpd
    import shapely
    from shapely.geometry import box
    india = shapely.union_all(gpd.read_file(STATES).to_crs(4326).geometry.values).buffer(0.05)
    return [f"N{lat:02d}E{lon:03d}" for lat in range(6, 39, 3) for lon in range(66, 99, 3)
            if box(lon, lat, lon + 3, lat + 3).intersects(india)]


def fetch(url: str, dest: Path, client: httpx.Client) -> str:
    head = client.head(url)
    if head.status_code == 404:
        return "missing upstream"
    size = int(head.headers.get("content-length", 0))
    if dest.exists() and size and dest.stat().st_size == size:
        return "ok (cached)"
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return f"ok ({dest.stat().st_size / 2**20:.0f} MB)"


def worldcover(out: Path):
    d = out / "ESA_WorldCover_2021_v200"
    d.mkdir(parents=True, exist_ok=True)
    tiles = india_tiles()
    print(f"WorldCover: {len(tiles)} tiles -> {d}", flush=True)
    with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True) as c:
        for i, t in enumerate(tiles, 1):
            for attempt in range(3):
                try:
                    status = fetch(WC_URL.format(tile=t), d / f"ESA_WorldCover_10m_2021_v200_{t}_Map.tif", c)
                    break
                except httpx.HTTPError as e:
                    status = f"retry ({e})"
            print(f"  [{i}/{len(tiles)}] {t}: {status}", flush=True)


def modis(out: Path, year: int):
    import earthaccess
    d = out / f"MODIS_MCD12Q1_061_{year}"
    d.mkdir(parents=True, exist_ok=True)
    auth = earthaccess.login(strategy="environment") if os.environ.get("EARTHDATA_USERNAME") else earthaccess.login(strategy="netrc")
    if not auth or not auth.authenticated:
        sys.exit("Earthdata login failed: set EARTHDATA_USERNAME / EARTHDATA_PASSWORD")
    res = earthaccess.search_data(short_name="MCD12Q1", version="061", bounding_box=(68, 6, 98, 38),
                                  temporal=(f"{year}-01-01", f"{year}-12-31"))
    print(f"MCD12Q1 {year}: {len(res)} granules -> {d}", flush=True)
    files = earthaccess.download(res, str(d))
    print(f"  downloaded {len(files)} files", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--only", choices=["worldcover", "modis"])
    a = ap.parse_args()
    if a.only in (None, "modis"):
        modis(a.out, a.year)
    if a.only in (None, "worldcover"):
        worldcover(a.out)
    print("done", flush=True)
