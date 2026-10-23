---
title: KPSTerra
emoji: 🌍
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: true
short_description: Earth observation, climate, water and fire by Katroth Premsingh
---

# KPSTerra: KPS + Earth

A platform for Earth observation, climate, water and fire by **Katroth Premsingh**.
Fire module: live NASA FIRMS fires, satellite tracking, 25 years of fire statistics for India, a Climate–Fire
Explorer, and a Rothermel fire-spread simulator on real terrain and land cover.

**Required secret** (Space → Settings → Variables and secrets): `FIRMS_MAP_KEY`, a free key from
https://firms.modaps.eosdis.nasa.gov/api/map_key/ . Without it the live-fire layer shows "unavailable"; everything else works.

Data credits: NASA FIRMS, NASA GIBS / Blue Marble, NOAA GFS, CelesTrak / SatNOGS / Space-Track, GDACS, NIFC,
ESA WorldCover 2021, MODIS MCD12Q1, ERA5-Land (Copernicus), IMD, Survey of India boundaries via NWIC, Esri basemaps.
