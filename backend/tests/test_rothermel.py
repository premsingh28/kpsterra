"""Rothermel/Albini implementation checked against the expected values in the US Forest Service Fire Lab
`behave` library unit tests (github.com/firelab/behave, src/testBehave/testBehave.cpp)."""
import pytest

from app.services import rothermel as R

GS4_LOW = {"1h": 6, "10h": 7, "100h": 8, "herb": 60, "woody": 90}
MPH = 1 / 0.621371                     # 1 mph in km/h
CANOPY = dict(canopy_cover_pct=50, canopy_height_m=30 * 0.3048, crown_ratio=0.5)


def chains_per_hour(m_min):
    return m_min / 0.3048 * 60 / 66


@pytest.fixture
def gs4_upslope():
    # behave: upslope mode, 5 mph 20-ft wind blowing upslope, 30 % slope, aspect 0, canopy 50 % / 30 ft / 0.5
    return R.surface_fire(124, GS4_LOW, 5 * MPH, 0, 30, 0, **CANOPY)


def test_gs4_fuelbed_intermediates(gs4_upslope):
    b = gs4_upslope["_base"]
    assert b["mx_live"] * 100 == pytest.approx(137.968551, abs=1e-5)
    assert b["sigma"] == pytest.approx(1631.128734, abs=1e-5)
    assert b["mf_dead"] * 100 == pytest.approx(6.005463, abs=1e-5)
    assert b["mf_live"] * 100 == pytest.approx(85.874007, abs=1e-5)


def test_gs4_spread_rates(gs4_upslope):
    r = gs4_upslope
    assert chains_per_hour(r["ros_head_m_min"]) == pytest.approx(8.876216, abs=1e-5)
    assert chains_per_hour(r["ros_back_m_min"]) == pytest.approx(2.91614659, abs=1e-5)
    assert chains_per_hour(r["ros_flank_m_min"]) == pytest.approx(5.08766627, abs=1e-5)


def test_gs4_fireline_intensity(gs4_upslope):
    assert gs4_upslope["fireline_intensity_kw_m"] / 3.46414 == pytest.approx(598.339039, abs=1e-3)


def test_gs4_heat_source_flat():
    r = R.surface_fire(124, GS4_LOW, 5 * MPH, 0, 0, 0, **CANOPY)
    w = r["_ws"]
    assert r["_base"]["heat_source"] * (1 + w["phi_w"] + w["phi_s"]) == pytest.approx(1164.267376, abs=1e-4)


def test_fm4_cross_slope_wind():
    # behave: FM4, wind from 90 deg, aspect 0, 5 mph 20-ft, slope 30 DEGREES, canopy cover 40 %
    r = R.surface_fire(4, GS4_LOW, 5 * MPH, 270, 57.735027, 0, canopy_cover_pct=40, canopy_height_m=9.144)
    assert chains_per_hour(r["ros_head_m_min"]) == pytest.approx(46.631688, abs=1e-4)


def test_length_to_width_ratio():
    assert R.length_to_width(0) == 1.0
    assert R.length_to_width(5 * 88) == pytest.approx(1.590064, abs=1e-6)   # behave: 5 mph midflame, flat


def test_no_wind_no_slope_is_circular_and_moisture_kills_fire():
    r = R.surface_fire(1, {"1h": 6, "10h": 7, "100h": 8, "herb": 60, "woody": 90}, 0, 0, 0, 0)
    assert r["length_to_width"] == 1.0 and r["ros_back_m_min"] == pytest.approx(r["ros_head_m_min"])
    wet = R.surface_fire(1, {"1h": 13, "10h": 14, "100h": 15, "herb": 60, "woody": 90}, 10, 0, 0, 0)   # Mx = 12 %
    assert wet["burnable"] is False


def test_monotonic_in_wind_and_slope():
    base = dict(fuel=9, moisture_pct={"1h": 5, "10h": 6, "100h": 8, "herb": 60, "woody": 90}, wind_from_deg=0, aspect_deg=0)
    ros = [R.surface_fire(wind_20ft_kmh=w, slope_pct=0, **base)["ros_head_m_min"] for w in (0, 5, 10, 20)]
    assert ros == sorted(ros) and ros[0] < ros[-1]
    ros_s = [R.surface_fire(wind_20ft_kmh=0, slope_pct=s, **base)["ros_head_m_min"] for s in (0, 20, 40, 60)]
    assert ros_s == sorted(ros_s)


def test_direction_of_max_spread():
    # wind from the west on flat ground -> fire spreads east (90 deg)
    r = R.surface_fire(1, GS4_LOW, 15, 270, 0, 0)
    assert r["dir_max_spread_deg"] == pytest.approx(90, abs=1e-6)
    # no wind on a north-facing slope (aspect 0) -> fire runs upslope, i.e. south (180)
    r = R.surface_fire(1, GS4_LOW, 0, 0, 40, 0)
    assert r["dir_max_spread_deg"] == pytest.approx(180, abs=1e-6)
