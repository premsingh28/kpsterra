# KPSTerra

**KPS + Earth.** A broad platform for Earth observation, climate, water and fire, built by Katroth Premsingh.

Fire is the first module: an interactive globe with live NASA FIRMS detections, satellite orbit estimates, 25 years of fire statistics for India, a Climate–Fire Explorer, and a Rothermel fire-spread simulator on real terrain and land cover.

## Run it on your PC

```powershell
cd E:\Prem\Research_works\firescope\backend
& "C:\Users\Katroth Prem\miniconda3\python.exe" -m pip install -r requirements.txt
& "C:\Users\Katroth Prem\miniconda3\python.exe" scripts\build_history.py      # once; ~1 min
& "C:\Users\Katroth Prem\miniconda3\python.exe" scripts\build_climate.py      # once; ERA5-Land + IMD → state-month, ~5 min
& "C:\Users\Katroth Prem\miniconda3\python.exe" -m uvicorn app.main:app --port 8000
```
Open http://localhost:8000. API docs are at http://localhost:8000/docs.

`FIRMS_MAP_KEY` is read from the environment (already set on this PC with `setx`). On another machine, copy `.env.example` and set the variable. The key stays on the server and is never sent to the browser.

Tests:
- `python -m pytest` in `backend/` runs 25 tests: SGP4/geodetic conversion, Mann–Kendall, anomalies, FIRMS parsing, API validation, plus correlation, effective n, OLS/VIF, FDR, RH/VPD and deseasonalising.
- Browser statistics: run `python scripts/make_js_fixture.py`, then open http://localhost:8000/tests/climstats.html. It checks `js/climstats.js` against the Python/scipy reference (269 checks).

## Structure
```
backend/app/
  main.py              API routes, CORS, serves the frontend
  config.py            settings, FIRMS products, satellite catalogue
  http.py, cache.py    timeouts, retries with backoff, TTL cache (serves stale data if upstream is down)
  services/firms.py    FIRMS NRT ingestion and normalisation
  services/orbits.py   CelesTrak elements, SGP4, TEME→geodetic
  services/stats.py    yearly/monthly/seasonal stats, anomaly, Mann–Kendall, Sen slope
  services/history.py  custom-polygon queries on the MODIS archive
backend/scripts/build_history.py   archive → static JSON + parquet
frontend/              static site (no build step): MapLibre GL 5, satellite.js, ECharts
  data/                precomputed JSON (states, stats, 0.25° grid, dataset catalogue)
  js/                  config, map, fires, satellites, history, stats, draw, pages, main
```

## API
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | key configured? history loaded? |
| GET | `/api/fires/live?source=VIIRS_NOAA20_NRT&days=1&region=india` | FIRMS NRT as GeoJSON; `days` 1–5; `region` india/world; cached 15 min |
| GET | `/api/satellites` | elements, epoch, element age, element source and current SGP4 position for 9 satellites. Sources are tried in order: CelesTrak → SatNOGS DB (Space-Track) → TLE API mirror. Elements are cached on disk for 6 h (`backend/cache/tle_cache.json`), and the last good set is used, flagged as stale, if every source is down. |
| GET | `/api/satellites/{norad}/track?minutes=100` | ground track |
| POST | `/api/stats/polygon` `{geometry, start?, end?, min_confidence?}` | statistics inside a drawn polygon (MODIS archive) |
| GET | `/api/layers/wind` | latest NOAA GFS 10 m wind, 1° grid (tenths of m/s); cached 1 h; decoded with eccodes in a subprocess |
| GET | `/api/layers/gdacs` | current GDACS disaster alerts and tropical-cyclone tracks; cached 15 min |
| GET | `/api/layers/incidents?region=us\|canada` | official wildfire incidents with agency status (NIFC WFIGS / CWFIS); cached 15 min |
| GET | `/api/layers/gibs-times` | latest available time of each NASA GIBS imagery layer |
| GET | `/api/sim/fuel-models` | fuel models available to the simulator |
| GET | `/api/sim/fuel-crosswalk` | land-cover class → fuel model table used for `fuel_mode: "landcover"` |
| POST | `/api/sim/rothermel` `{lat, lon, fuel, moisture{1h,10h,100h,herb,woody}, wind_20ft_kmh, wind_from_deg, hours, waf?, canopy_cover_pct?, canopy_height_m?}` | Rothermel spread from a point: perimeters (GeoJSON), arrival-time PNG, point fire behaviour |

## Feature status
**Working**
- **Live map design:**
  - Starfield globe; right-hand icon rail (layers, basemap, satellites, wind, measure, draw area, share link, PNG, legend, statistics); live IST/UTC clock.
  - Searchable layer list.
  - Basemaps: satellite + labels, dark, light, streets, topographic, NASA VIIRS true colour, Black Marble night lights. Views: globe, flat 2D, or **3D terrain** (AWS Open Data elevation tiles, 1.6× exaggeration, hillshading).
  - Satellites are coloured by sensor (VIIRS / MODIS / SLSTR / OLI). Landsat fades over the night side. Selecting a satellite shows its 12-hour ground track.
  - Hotspot clusters are coloured High / Medium / Low activity (thresholds in `js/config.js`). GDACS alerts have type and alert-level icons.
  - The legend has sections, generated from the same colours the layers use. The map position is kept in the URL.
- **Live context layers:**
  - Animated GFS 10 m wind particles.
  - Himawari IR clouds over Asia (10-min); GOES-East/West GeoColor.
  - OMPS UV aerosol index (smoke/dust); MAIAC aerosol optical depth.
  - GDACS disaster alerts and cyclone tracks.
  - USA official incidents (NIFC) coloured by agency-reported status.
  - Canada (CWFIS) is wired up, but the server was unreachable from this network.
- Great-circle distance measuring tool.
- **Rothermel fire-spread simulation** (flame button on the rail): click an ignition point, set the inputs, run.
  - **Inputs:** Anderson fuel models 1–13 + GS4, with India hints for each; 1-h/10-h/100-h/live moisture; wind auto-filled from live GFS at that point; canopy sheltering or a WAF override; duration 1–24 h.
  - **Physics** (`services/rothermel.py`): Rothermel (1972) with Albini (1976) size-class weighting, live moisture of extinction, dynamic herb curing, the wind limit, wind–slope vector combination, an elliptical fire shape, Byram intensity and flame length.
  - **Validation:** reproduces the expected values in the USFS Fire Lab `behave` (BehavePlus) unit tests to 6 decimals: GS4 spread, backing and flanking rates, live Mx, characteristic SAV and moistures, fireline intensity, heat source; FM4 spread; length-to-width ratio (`tests/test_rothermel.py`).
  - **Spread** (`services/firesim.py`): AWS Open Data terrain (~30 m) → slope/aspect → per-cell Rothermel → minimum-travel-time arrival on a 16-neighbour grid (SciPy Dijkstra). The domain is sized automatically. On flat ground it reproduces the analytic ellipse within grid tolerance (`tests/test_firesim.py`).
  - **Outputs:** hourly perimeters, an arrival-time map, area-over-time chart, spread rates, direction, flame length, fireline intensity with a fire-intensity class (hauling chart), and GeoJSON/JSON downloads.
  - **Land-cover sources** (choose in the panel):
    - **Recent** (default): ESA WorldCover 2021 (10 m; majority class per cell) for structure and non-burnable surfaces, with MODIS MCD12Q1 2025 typing the tree pixels. Leaf type comes from the PFT layer and mixed forest from IGBP, because IGBP labels open chir-pine forest as "savanna".
      - Data: `python scripts/download_landcover.py` (68 WorldCover tiles, ~5 GB; 16 MODIS tiles, 129 MB; needs your Earthdata login), then `python scripts/build_modis_lc.py`.
      - Any WorldCover tile that isn't local is read from the public AWS copy.
    - **ORNL 2005/1995/1985:** kept for historical fires and comparison.
  - **Fuels from land cover** (`services/fuelmap.py`): each grid cell takes its fuel model from the chosen source.
    - Crosswalk:
      - Deciduous broadleaf, deciduous needleleaf and evergreen needleleaf forest (sal, teak, chir pine) → FM9
      - Evergreen broadleaf forest and plantations → FM8; mixed forest → FM10; shrubland → FM6
      - Cropland, fallow land and wasteland → FM1
      - Grassland → FM3 below 3000 m, FM1 at or above 3000 m
      - Water, built-up, barren, aquaculture, salt pan, wetlands, mangroves, snow & ice → non-burnable. These act as natural firebreaks.
      - Cells outside India use the selected fallback fuel.
    - Outputs: burned area per land-cover class and a fuel-map overlay. Ignitions on non-burnable land are rejected with a message.
    - The crosswalk is a documented assumption for pre-monsoon conditions, not a field-calibrated fuel map. Edit `CLASSES` to change it.
    - Tests: water stops the fire; grass outruns litter; the alpine rule applies; ignition on water is rejected.
  - **Limitations:** uniform moisture and weather; surface fire only (no crown fire or spotting); no suppression. The land cover dates from 2005. Large runs use cells coarser than 100 m. For research and teaching, not operational use.
- Live FIRMS fires (VIIRS NOAA-20/21, Suomi-NPP, MODIS):
  - Display as FRP-coloured points, heatmap or clusters.
  - Filters for confidence and minimum FRP; time slider with playback; age fading.
  - Detail popup in UTC and IST; CSV and GeoJSON export.
- Satellite tracking for Terra, Aqua, Suomi-NPP, NOAA-20, NOAA-21, Sentinel-3A/B and Landsat 8/9:
  - Positions update every second, with ground tracks and element age shown.
  - Filter by fire sensors or other Earth-observation satellites.
- Historical statistics from MODIS 2000–2026 (1.84 M vegetation-fire detections):
  - All-India and per-state cards, yearly bars with anomaly, seasonal cycle, monthly series and FRP histogram.
  - Mann–Kendall trend; CSV and parameter-JSON downloads.
- 0.25° density grid shown as flat cells or 3D columns, per year or as the yearly mean.
- Custom-polygon statistics; state click and state search; search by "lat, lon".
- Fire Analytics page (state ranking, comparison, summary table), India Dashboard (state selector, year-on-year comparison), searchable Data Catalogue, About page with methods and limitations.
- Responsive layout for desktop, tablet and phone. Map export to PNG (HTML satellite labels are not included in the PNG).

- **Climate–Fire Explorer.** Uses your ERA5-Land monthly and IMD gridded data, aggregated to state × month for 2001–2025 by `scripts/build_climate.py`. The analysis runs in the browser, so it needs no backend.
  - Inputs: region, fire metric (log count, count or mean FRP) and 10 variables (IMD rain/Tmax/Tmin; ERA5-Land T2m, RH, VPD, precipitation, soil moisture, wind, LAI).
  - Options: season months; monthly or one-value-per-year aggregation; lag 0–6 months; anomaly and detrend switches; Pearson or Spearman.
  - Results: r, p, an autocorrelation-adjusted p (effective n) and missing-data counts, with time-series, scatter-with-OLS, lag and all-variable charts.
  - Multiple regression with standardised coefficients, VIF and Durbin–Watson.
  - 0.5° Spearman correlation maps (Feb–May anomalies, FDR-corrected).
  - CSV and JSON-parameter downloads.

**Partial**
- Legend: the official fire-status categories are listed but intentionally empty, because no authoritative incident feed exists for India.
- India dashboard: state level only. District boundaries are not loaded yet.

**Planned**
- Climate–Fire Explorer additions: MODIS NDVI, SPEI drought, GLEAM evaporative stress, and custom-polygon climate series (needs the backend).
- Fire Danger page (GEFF/GWIS FWI).
- Burned area and smoke (MCD64A1, GFED, CAMS).
- VIIRS archive history.
- Research Workspace with saved projects and reports.
- Scheduled GitHub Action for hosting with no backend.

## Deploying (current method: one Hugging Face Space, free)
1. `python deploy/build_hf_space.py` assembles `deploy/hf-space/` (~33 MB: code, frontend, MODIS land cover, fire archive parquet). No secrets are included.
2. Once, in a terminal: `hf auth login` with a **write** token from https://huggingface.co/settings/tokens.
3. `python deploy/deploy_hf.py`: creates or updates the Space `<you>/kpsterra` and uploads the folder.
4. In the Space → Settings → Variables and secrets, add the secret **`FIRMS_MAP_KEY`**.
5. The app goes live at `https://<you>-kpsterra.hf.space` after the Docker build (~5–10 min). ESA WorldCover and terrain are read from AWS Open Data at runtime.

### GitHub (code + website copy)
- Repository: `github.com/premsingh28/kpsterra`. Pushing to `main` runs `.github/workflows/pages.yml`, which publishes `frontend/` to **https://premsingh28.github.io/kpsterra**.
- Set the repository variable `KPSTERRA_API` (Settings → Secrets and variables → Actions → Variables) to the Space URL, e.g. `https://<hf-user>-kpsterra.hf.space`.
- Enable Pages with Settings → Pages → Source: **GitHub Actions**.

## Deploying for free (alternative: split frontend and backend)
1. **Frontend → GitHub Pages.** Push the repo and enable Pages on the `/frontend` folder. Use a GitHub Action or move it to `/docs`. The site reads the backend URL from `?api=` or `window.KPSTERRA_API` (set in `js/config.js`).
2. **Backend → Hugging Face Spaces (Docker, free).**
   - Copy `backend/` and the built `backend/cache/modis_india.parquet` (25 MB) into the Space.
   - Add `FIRMS_MAP_KEY` as a Space **secret**.
   - Set `ALLOWED_ORIGINS` to your GitHub Pages URL.
   - Render's free tier works too, but it sleeps after 15 minutes idle.
3. Without a backend, the state statistics, grid and catalogue still work. Live fires, satellites and polygon statistics show clear "unavailable" messages.

## Data, attribution and limitations
- NASA FIRMS (LANCE/EOSDIS), CelesTrak, NASA GIBS, Esri basemaps, and Survey of India boundaries via NWIC. Full details are in the in-app Data Catalogue.
- Detections are hot pixels, not incidents, and not burned area. Counts depend on overpasses, cloud and sensor. MODIS orbit drift since 2022–23 affects recent trends.
- Satellite positions are SGP4 estimates from published elements, not telemetry. KPSTerra does not know whether an instrument is imaging.
- History uses MODIS type 0 (presumed vegetation fire). The 2000 and 2026 years are partial, and an incomplete final year is excluded from trend tests.
- Activity classes for the grid are low < 10, medium 10–50 and high > 50 detections per cell per year (`js/config.js`).
