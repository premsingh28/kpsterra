"""The grid travel-time spread must reproduce the analytic Rothermel ellipse on flat, uniform terrain."""
import math

import numpy as np
import pytest

from app.services import firesim as F
from app.services import rothermel as R

M = {"1h": 6, "10h": 8, "100h": 10, "herb": 60, "woody": 90}
flat = lambda lon, lat: np.zeros_like(lon)  # noqa: E731


def _reach(res, bearing_deg, t_min):
    """Distance (m) from ignition to the arrival-time isochrone t along a bearing."""
    arr = res["_arrival_min"]
    xx, yy = res["_xy_m"]
    b = math.radians(bearing_deg)
    best = 0.0
    for d in np.arange(0, xx.max(), 5.0):
        x, y = d * math.sin(b), d * math.cos(b)
        j = int(round(x / res["inputs"]["cell_m"])) + arr.shape[1] // 2
        i = arr.shape[0] // 2 - int(round(y / res["inputs"]["cell_m"]))
        if not (0 <= i < arr.shape[0] and 0 <= j < arr.shape[1]) or arr[i, j] > t_min:
            break
        best = d
    return best


@pytest.mark.parametrize("wind_kmh", [0.0, 15.0])
def test_flat_terrain_matches_analytic_ellipse(wind_kmh):
    hours = 2.0
    res = F.simulate(20.0, 80.0, 1, M, wind_kmh, 270, hours=hours, half_extent_km=6, cell_m=30, elevation_fn=flat)
    p = R.surface_fire(1, M, wind_kmh, 270, 0, 0)
    t = hours * 60
    head = p["ros_head_m_min"] * t
    back = p["ros_back_m_min"] * t
    assert p["dir_max_spread_deg"] == pytest.approx(90 if wind_kmh else p["dir_max_spread_deg"])
    # head (downwind = east) and back (west) distances within 6 % (grid discretisation)
    assert _reach(res, 90, t) == pytest.approx(head, rel=0.06)
    assert _reach(res, 270, t) == pytest.approx(back, rel=0.08, abs=40)
    # burned area vs ellipse area pi*a*b, a = (head+back)/2, b = a / LWR
    a = (head + back) / 2
    area_ha = math.pi * a * (a / p["length_to_width"]) / 1e4
    assert res["final_area_ha"] == pytest.approx(area_ha, rel=0.08)


def test_sim_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(F, "elevation", flat)
    c = TestClient(main.app)
    r = c.post("/api/sim/rothermel", json={"lat": 20, "lon": 80, "fuel": 9, "moisture": {"1h": 6, "10h": 8, "100h": 10},
                                           "wind_20ft_kmh": 12, "wind_from_deg": 270, "hours": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["burnable"] and body["perimeters"]["features"] and body["arrival_png"].startswith("data:image/png")
    assert "_arrival_min" not in body
    assert c.post("/api/sim/rothermel", json={"lat": 20, "lon": 80, "fuel": 999}).status_code == 422
    assert c.post("/api/sim/rothermel", json={"lat": 20, "lon": 80, "fuel": 1, "hours": 100}).status_code == 422
    assert len(c.get("/api/sim/fuel-models").json()) == 14


def _lc(fn):
    """classes_fn from a function of local x (m east of 80°E at 20°N)."""
    def classes(lon, lat):
        x = (lon - 80.0) * F.M_PER_DEG_LON_EQ * math.cos(math.radians(20.0))
        return fn(x).astype(np.uint8)
    return classes


def test_water_is_a_firebreak():
    # deciduous forest (FM9) everywhere except a 200 m river 300-500 m east of the ignition; wind from the west
    river = _lc(lambda x: np.where((x > 300) & (x < 500), 9, 1))
    res = F.simulate(20.0, 80.0, 9, M, 20, 270, hours=6, half_extent_km=2, cell_m=30, elevation_fn=flat,
                     fuel_mode="landcover", classes_fn=river)
    arr, (xx, _) = res["_arrival_min"], res["_xy_m"]
    assert np.isinf(arr[xx > 520]).all()                 # nothing beyond the river burns
    assert (arr[(xx > 0) & (xx < 280)] <= 360).any()     # but the fire did reach the near bank
    water = next(s for s in res["landcover_summary"] if s["class"] == 9)
    assert water["burned_ha"] == 0 and water["fuel"] == "NB"


def test_ignition_on_water_is_rejected():
    res = F.simulate(20.0, 80.0, 9, M, 10, 270, hours=1, half_extent_km=1.5, cell_m=60, elevation_fn=flat,
                     fuel_mode="landcover", classes_fn=_lc(lambda x: np.full(x.shape, 9)))
    assert res["burnable"] is False and "water bodies" in res["reason"]


def test_grass_spreads_faster_than_litter():
    # grassland (FM3) west half, deciduous litter (FM9) east half; no wind, flat
    split = _lc(lambda x: np.where(x < 0, 14, 1))
    res = F.simulate(20.0, 80.0, 9, M, 0, 0, hours=6, half_extent_km=3, cell_m=30, elevation_fn=flat,
                     fuel_mode="landcover", classes_fn=split)
    assert _reach(res, 270, 360) > 3 * _reach(res, 90, 360)
    fuels = {s["class"]: s["fuel"] for s in res["landcover_summary"]}
    assert fuels == {14: "FM3", 1: "FM9"}


def test_alpine_grassland_rule():
    from app.services import fuelmap
    cls = np.array([[14, 14, 9, 127]], np.uint8)
    z = np.array([[1000.0, 3500.0, 100.0, 0.0]])
    assert fuelmap.fuel_grid(cls, z, fallback_fuel=2).tolist() == [[3, 1, 0, 2]]


def test_recent_crosswalk_rules():
    from app.services import fuelmap as FMap
    #           shrub grass  grass  crop water built  ENF   ENF   DBF   EBF   mixed open-wood tree-other nodata
    cls = np.array([[20, 30, 30, 40, 80, 50, 1101, 1101, 1104, 1102, 1105, 1106, 1100, 0]], np.int16)
    z = np.array([[500, 1000, 3200, 200, 100, 300, 1800, 3000, 600, 900, 1500, 400, 700, 0]], float)
    assert FMap.fuel_grid(cls, z, 2, FMap.RECENT).tolist() == [[6, 3, 1, 1, 0, 0, 9, 8, 9, 8, 10, 2, 9, 2]]


def test_tree_typing_uses_pft_not_igbp_savanna():
    from app.services import fuelmap as FMap
    # IGBP woody savanna (8) with PFT evergreen needleleaf (1) = open chir pine -> needleleaf, not savanna
    igbp = np.array([8, 9, 9, 5, 4, 8, 255], np.uint8)
    pft = np.array([1, 2, 6, 1, 4, 5, 255], np.uint8)
    assert FMap.tree_codes(igbp, pft).tolist() == [1101, 1102, 1106, 1105, 1104, 1107, 1100]


def test_worldcover_tile_names():
    from app.services import fuelmap as FMap
    assert list(FMap._wc_tiles((79.5, 29.5, 79.8, 29.8))) == ["N27E078"]
    assert set(FMap._wc_tiles((80.9, 26.9, 81.1, 27.1))) == {"N24E078", "N24E081", "N27E078", "N27E081"}


def test_recent_landcover_real_data():
    """Uses local WorldCover/MODIS files when present (skipped otherwise)."""
    from app.services import fuelmap as FMap
    if not (FMap.MODIS_TIF.exists() and (FMap.WC_DIR / "ESA_WorldCover_10m_2021_v200_N27E078_Map.tif").exists()):
        pytest.skip("local WorldCover/MODIS tiles not available")
    xs, ys = np.meshgrid(np.linspace(79.60, 79.70, 51), np.linspace(29.70, 29.60, 51))
    cls, legend = FMap.sample("recent", xs, ys)
    codes = set(np.unique(cls).tolist())
    assert codes <= set(legend) and any(c >= 1000 for c in codes)     # Almora hills: tree cover with MODIS types


def test_nonburnable_moisture_reports_reason():
    wet = {"1h": 30, "10h": 30, "100h": 30, "herb": 60, "woody": 90}
    res = F.simulate(20.0, 80.0, 1, wet, 10, 270, hours=1, half_extent_km=1.5, cell_m=60, elevation_fn=flat)
    assert res["burnable"] is False and "moisture of extinction" in res["reason"]


def test_fire_runs_upslope_without_wind():
    # plane rising to the north: fire should advance further north than south
    ramp = lambda lon, lat: (lat - 20.0) * 110_540 * 0.3   # noqa: E731  (30 % slope, facing south)
    res = F.simulate(20.0, 80.0, 9, M, 0, 0, hours=2, half_extent_km=2, cell_m=30, elevation_fn=ramp)
    assert res["ignition"]["slope_pct"] == pytest.approx(30, abs=0.5)
    assert _reach(res, 0, 120) > 2 * _reach(res, 180, 120)
