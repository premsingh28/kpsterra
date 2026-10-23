"""Assemble a self-contained folder for the Hugging Face Docker Space (deploy/hf-space/).

Copies the backend code, the static frontend, and the small data files the server needs at runtime:
  backend/cache/modis_india.parquet (custom-polygon statistics) and the MODIS MCD12Q1 land-cover GeoTIFF.
ESA WorldCover is not copied (≈5 GB): the server reads it directly from the public AWS copy.
Secrets are never copied: FIRMS_MAP_KEY is set as a Space secret in the Hugging Face settings.

Usage: python deploy/build_hf_space.py
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "hf-space"
LC = Path(r"E:\Prem\Research_works\PhDFireResearch\01_Raw_Data\LandCover")
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "cache", "tests", "*.part", ".env")


def main():
    for sub in ("backend", "frontend", "data"):
        shutil.rmtree(OUT / sub, ignore_errors=True)
    shutil.copytree(ROOT / "backend", OUT / "backend", ignore=SKIP)
    shutil.copytree(ROOT / "frontend", OUT / "frontend", ignore=shutil.ignore_patterns("tests"))
    (OUT / "backend" / "cache").mkdir(parents=True)
    shutil.copy2(ROOT / "backend" / "cache" / "modis_india.parquet", OUT / "backend" / "cache")
    modis = LC / "MODIS_MCD12Q1_061_2025"
    dest = OUT / "data" / "landcover" / modis.name
    dest.mkdir(parents=True)
    shutil.copy2(modis / "MCD12Q1_2025_IGBP_India_4326.tif", dest)
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    leaked = [f for f in OUT.rglob("*") if f.is_file() and f.name in (".env", ".netrc", ".cdsapirc")]
    assert not leaked, f"secret files would be uploaded: {leaked}"
    print(f"built {OUT} ({total / 2**20:.1f} MB)")


if __name__ == "__main__":
    main()
