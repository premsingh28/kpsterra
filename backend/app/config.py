"""Server configuration. All secrets come from environment variables, never from the client."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # firescope/
DATA_DIR = ROOT / "frontend" / "data"                # precomputed static data (served to the browser)
HISTORY_PARQUET = ROOT / "backend" / "cache" / "modis_india.parquet"

FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"

HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "45"))
FIRES_CACHE_SECONDS = int(os.environ.get("FIRES_CACHE_SECONDS", "900"))      # 15 min
TLE_CACHE_SECONDS = int(os.environ.get("TLE_CACHE_SECONDS", "21600"))        # 6 h
ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o]

# FIRMS NRT products this app exposes.
FIRMS_SOURCES = {
    "VIIRS_NOAA20_NRT": "VIIRS 375 m · NOAA-20",
    "VIIRS_NOAA21_NRT": "VIIRS 375 m · NOAA-21",
    "VIIRS_SNPP_NRT": "VIIRS 375 m · Suomi-NPP",
    "MODIS_NRT": "MODIS 1 km · Terra/Aqua",
}

# Satellites whose CelesTrak elements were verified on 2026-10-23.
SATELLITES = {
    25994: {"name": "Terra", "mission": "EOS", "type": "fire", "sensors": ["MODIS", "ASTER", "MISR", "CERES", "MOPITT"]},
    27424: {"name": "Aqua", "mission": "EOS", "type": "fire", "sensors": ["MODIS", "AIRS", "AMSU-A", "CERES"]},
    37849: {"name": "Suomi-NPP", "mission": "JPSS", "type": "fire", "sensors": ["VIIRS", "CrIS", "ATMS", "OMPS"]},
    43013: {"name": "NOAA-20", "mission": "JPSS", "type": "fire", "sensors": ["VIIRS", "CrIS", "ATMS", "OMPS"]},
    54234: {"name": "NOAA-21", "mission": "JPSS", "type": "fire", "sensors": ["VIIRS", "CrIS", "ATMS", "OMPS"]},
    41335: {"name": "Sentinel-3A", "mission": "Copernicus", "type": "earth", "sensors": ["SLSTR", "OLCI", "SRAL"]},
    43437: {"name": "Sentinel-3B", "mission": "Copernicus", "type": "earth", "sensors": ["SLSTR", "OLCI", "SRAL"]},
    39084: {"name": "Landsat 8", "mission": "Landsat", "type": "earth", "sensors": ["OLI", "TIRS"]},
    49260: {"name": "Landsat 9", "mission": "Landsat", "type": "earth", "sensors": ["OLI-2", "TIRS-2"]},
}
