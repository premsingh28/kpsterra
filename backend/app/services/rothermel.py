"""Rothermel (1972) surface fire spread with Albini (1976) multi-class weighting, following the
conventions of the US Forest Service `behave` library (BehavePlus):

- standard fuel models (Anderson 1982; Scott & Burgan 2005 dynamic models with herbaceous curing)
- wind adjustment factor from canopy sheltering (Albini & Baughman 1979) or fuel-bed depth
- vector combination of wind and slope effects (direction of maximum spread)
- elliptical fire shape (length-to-width ratio as in behave), backing and flanking spread
- Byram fireline intensity and flame length

Units inside the model are imperial (lb, ft, min, Btu), as in the original papers; the public
`surface_fire` function converts to SI.
"""
import math
from dataclasses import dataclass

# ---------------------------------------------------------------- fuel models
# loads t/ac: 1h, 10h, 100h, live herb, live woody; SAV ft^-1: 1h, live herb, live woody; depth ft; Mx %
@dataclass(frozen=True)
class FuelModel:
    code: str
    name: str
    load: tuple            # (1h, 10h, 100h, herb, woody) lb/ft2
    sav: tuple             # (1h, herb, woody) 1/ft
    depth: float           # ft
    mx_dead: float         # %
    dynamic: bool = False
    heat: float = 8000.0   # Btu/lb
    india_hint: str = ""


_T = 2000.0 / 43560.0   # tons/acre -> lb/ft2 (Scott & Burgan models are published in t/ac)

# Anderson (1982) loads in lb/ft2 exactly as tabulated in behave / BehavePlus
FUEL_MODELS = {
    1: FuelModel("FM1", "Short grass (1 ft)", (0.034, 0, 0, 0, 0), (3500, 1500, 1500), 1.0, 12, india_hint="Short dry grassland, cured pasture"),
    2: FuelModel("FM2", "Timber (grass and understory)", (0.092, 0.046, 0.023, 0.023, 0), (3000, 1500, 1500), 1.0, 15, india_hint="Open dry deciduous forest with grass understory"),
    3: FuelModel("FM3", "Tall grass (2.5 ft)", (0.138, 0, 0, 0, 0), (1500, 1500, 1500), 2.5, 25, india_hint="Terai / savanna tall grassland"),
    4: FuelModel("FM4", "Chaparral (6 ft)", (0.230, 0.184, 0.092, 0, 0.230), (2000, 1500, 1500), 6.0, 20, india_hint="Dense tall scrub (extreme)"),
    5: FuelModel("FM5", "Brush (2 ft)", (0.046, 0.023, 0, 0, 0.092), (2000, 1500, 1500), 2.0, 20, india_hint="Lantana / young shrub thicket"),
    6: FuelModel("FM6", "Dormant brush, hardwood slash", (0.069, 0.115, 0.092, 0, 0), (1750, 1500, 1500), 2.5, 25, india_hint="Dry scrub forest, dormant shrubs"),
    7: FuelModel("FM7", "Southern rough", (0.052, 0.086, 0.069, 0, 0.017), (1750, 1500, 1500), 2.5, 40, india_hint="Flammable shrub understory under pine"),
    8: FuelModel("FM8", "Closed timber litter", (0.069, 0.046, 0.115, 0, 0), (2000, 1500, 1500), 0.2, 30, india_hint="Compact litter under closed evergreen canopy"),
    9: FuelModel("FM9", "Hardwood / long-needle litter", (0.134, 0.019, 0.007, 0, 0), (2500, 1500, 1500), 0.2, 25, india_hint="Sal / teak / mixed deciduous leaf litter; chir pine needle litter (pre-monsoon)"),
    10: FuelModel("FM10", "Timber (litter and understory)", (0.138, 0.092, 0.230, 0, 0.092), (2000, 1500, 1500), 1.0, 25, india_hint="Pine / deciduous forest with heavy dead fuel"),
    11: FuelModel("FM11", "Light logging slash", (0.069, 0.207, 0.253, 0, 0), (1500, 1500, 1500), 1.0, 15, india_hint="Light logging debris"),
    12: FuelModel("FM12", "Medium logging slash", (0.184, 0.644, 0.759, 0, 0), (1500, 1500, 1500), 2.3, 20, india_hint="Medium slash"),
    13: FuelModel("FM13", "Heavy logging slash", (0.322, 1.058, 1.288, 0, 0), (1500, 1500, 1500), 3.0, 25, india_hint="Heavy slash"),
    124: FuelModel("GS4", "High-load humid grass-shrub", tuple(x * _T for x in (1.9, 0.3, 0.1, 3.4, 7.1)), (1800, 1600, 1600), 2.1, 40, dynamic=True,
                   india_hint="Tall humid grass with shrubs (NE India, Western Ghats grassland-shrub mosaics)"),
}

# Wind adjustment factors for unsheltered fuel beds (Albini & Baughman 1979; BehavePlus tables)
def unsheltered_waf(depth_ft: float) -> float:
    return 1.83 / math.log((20 + 0.36 * depth_ft) / (0.13 * depth_ft))


def sheltered_waf(canopy_cover: float, canopy_height_ft: float, crown_ratio: float) -> float | None:
    """Albini & Baughman (1979) under-canopy WAF; None (unsheltered) if crown fill < 5% or canopy < 6 ft, as in behave."""
    fill = canopy_cover * crown_ratio / 3.0
    if canopy_cover < 1e-7 or fill < 0.05 or canopy_height_ft < 6.0:
        return None
    h = canopy_height_ft
    return 0.555 / (math.sqrt(fill * h) * math.log((20 + 0.36 * h) / (0.13 * h)))


# ---------------------------------------------------------------- core model
RHO_P = 32.0          # particle density lb/ft^3
S_T = 0.0555          # total mineral content
S_E = 0.010           # effective mineral content
SAV_10H, SAV_100H = 109.0, 30.0


def _size_class_bin(sav: float) -> int:
    for i, lim in enumerate((1200, 192, 96, 48, 16)):
        if sav >= lim:
            return i
    return 5


def _particles(fm: FuelModel, m: dict):
    """Return dead and live particle lists [(load lb/ft2, sav, moisture fraction)], applying dynamic curing."""
    l1, l10, l100, lh, lw = fm.load
    s1, sh, sw = fm.sav
    dead = [(l1, s1, m["1h"]), (l10, SAV_10H, m["10h"]), (l100, SAV_100H, m["100h"])]
    live = []
    herb_dead = 0.0
    if fm.dynamic and lh > 0:
        # herbaceous curing (Scott & Burgan 2005), in the linear form behave/BehavePlus use
        mh = m["herb"]
        cured = 1.0 if mh < 0.30 else 0.0 if mh > 1.20 else 1.333 - 1.11 * mh
        herb_dead, lh = lh * cured, lh * (1 - cured)
    dead.append((herb_dead, sh, m["1h"]))           # cured herbaceous fuel behaves as 1-h dead fuel
    live = [(lh, sh, m["herb"]), (lw, sw, m["woody"])]
    return dead, live


def _category(parts):
    area = [w * s / RHO_P for w, s, _ in parts]
    a = sum(area)
    f = [x / a if a > 0 else 0 for x in area]
    # size-class weighting g_ij (Albini 1976): sum of f over particles in the same SAV bin
    bins = [_size_class_bin(s) for _, s, _ in parts]
    g = [sum(f[k] for k in range(len(parts)) if bins[k] == bins[j]) for j in range(len(parts))]
    return a, f, g


def rothermel_no_wind(fm: FuelModel, m: dict) -> dict:
    """Fuel-bed properties and no-wind, no-slope spread rate (ft/min)."""
    dead, live = _particles(fm, m)
    a_d, f_d, g_d = _category(dead)
    a_l, f_l, g_l = _category(live)
    a_t = a_d + a_l
    fi_d, fi_l = (a_d / a_t, a_l / a_t) if a_t > 0 else (0, 0)

    sav_d = sum(f * s for f, (_, s, _) in zip(f_d, dead))
    sav_l = sum(f * s for f, (_, s, _) in zip(f_l, live))
    sigma = fi_d * sav_d + fi_l * sav_l
    total_load = sum(w for w, _, _ in dead + live)
    if sigma <= 0 or total_load <= 0:
        return {"burnable": False}

    rho_b = total_load / fm.depth
    beta = rho_b / RHO_P
    beta_op = 3.348 * sigma ** -0.8189
    ratio = beta / beta_op
    a_coef = 133.0 * sigma ** -0.7913
    gamma_max = sigma ** 1.5 / (495.0 + 0.0594 * sigma ** 1.5)
    gamma = gamma_max * ratio ** a_coef * math.exp(a_coef * (1 - ratio))

    mf_d = sum(f * mo for f, (_, _, mo) in zip(f_d, dead))
    mf_l = sum(f * mo for f, (_, _, mo) in zip(f_l, live))

    # live moisture of extinction (Albini 1976 as in behave)
    fine_dead = sum(w * math.exp(-138.0 / s) for w, s, _ in dead if s > 0)
    fine_live = sum(w * math.exp(-500.0 / s) for w, s, _ in live if s > 0)
    fine_dead_moist = sum(w * math.exp(-138.0 / s) * mo for w, s, mo in dead if s > 0)
    mx_d = fm.mx_dead / 100.0
    if fine_live > 0:
        mfd = fine_dead_moist / fine_dead if fine_dead > 0 else 0
        mx_l = max(mx_d, 2.9 * (fine_dead / fine_live) * (1 - mfd / mx_d) - 0.226)
    else:
        mx_l = mx_d

    def eta_m(mf, mx):
        if mx <= 0 or mf >= mx:
            return 0.0          # at or above moisture of extinction (avoid 1e-16 polynomial residue)
        r = mf / mx
        return max(0.0, 1 - 2.59 * r + 5.11 * r * r - 3.52 * r ** 3)

    eta_s = min(1.0, 0.174 * S_E ** -0.19)
    wn_d = sum(g * w * (1 - S_T) for g, (w, _, _) in zip(g_d, dead))
    wn_l = sum(g * w * (1 - S_T) for g, (w, _, _) in zip(g_l, live))
    ir_d = gamma * wn_d * fm.heat * eta_m(mf_d, mx_d) * eta_s
    ir_l = gamma * wn_l * fm.heat * eta_m(mf_l, mx_l) * eta_s
    ir = ir_d + ir_l                                                    # Btu/ft2/min

    xi = math.exp((0.792 + 0.681 * sigma ** 0.5) * (beta + 0.1)) / (192 + 0.2595 * sigma)
    qig = lambda mo: 250 + 1116 * mo  # noqa: E731
    hs_d = sum(f * math.exp(-138.0 / s) * qig(mo) for f, (_, s, mo) in zip(f_d, dead) if s > 0)
    hs_l = sum(f * math.exp(-138.0 / s) * qig(mo) for f, (_, s, mo) in zip(f_l, live) if s > 0)
    heat_sink = rho_b * (fi_d * hs_d + fi_l * hs_l)
    r0 = ir * xi / heat_sink if heat_sink > 0 else 0.0

    return {"burnable": r0 > 0, "r0": r0, "ir": ir, "xi": xi, "heat_sink": heat_sink, "sigma": sigma, "beta": beta,
            "beta_ratio": ratio, "rho_b": rho_b, "mx_live": mx_l, "mf_dead": mf_d, "mf_live": mf_l,
            "heat_source": ir * xi}


def wind_slope(base: dict, midflame_ftmin: float, slope_frac: float, wind_to_deg: float, upslope_deg: float,
               wind_limit: bool = True) -> dict:
    """Combine wind and slope (vector addition of wind and slope spread-rate increments, as in behave).
    Directions are compass bearings the fire is pushed *towards*. Returns head ROS (ft/min), direction, effective wind."""
    s = base["sigma"]
    c = 7.47 * math.exp(-0.133 * s ** 0.55)
    b = 0.02526 * s ** 0.54
    e = 0.715 * math.exp(-3.59e-4 * s)
    r0 = base["r0"]
    phi_w = c * midflame_ftmin ** b * base["beta_ratio"] ** -e if midflame_ftmin > 0 else 0.0
    phi_s = 5.275 * base["beta"] ** -0.3 * slope_frac ** 2
    # rate vectors (ft/min) in compass frame
    def vec(mag, deg):
        return mag * math.sin(math.radians(deg)), mag * math.cos(math.radians(deg))
    wx, wy = vec(r0 * phi_w, wind_to_deg)
    sx, sy = vec(r0 * phi_s, upslope_deg)
    x, y = wx + sx, wy + sy
    add = math.hypot(x, y)
    direction = (math.degrees(math.atan2(x, y)) + 360) % 360 if add > 1e-9 else upslope_deg
    phi_e = add / r0 if r0 > 0 else 0.0
    u_eff = ((phi_e * base["beta_ratio"] ** e) / c) ** (1 / b) if phi_e > 0 else 0.0   # ft/min
    limited = False
    if wind_limit and u_eff > 0.9 * base["ir"]:                       # Rothermel's wind limit
        u_eff = 0.9 * base["ir"]
        phi_e = c * u_eff ** b * base["beta_ratio"] ** -e
        limited = True
    ros = r0 * (1 + phi_e)
    return {"ros": ros, "dir": direction, "u_eff": u_eff, "phi_w": phi_w, "phi_s": phi_s, "phi_e": phi_e, "wind_limited": limited}


def length_to_width(u_eff_ftmin: float) -> float:
    u = u_eff_ftmin / 88.0                                             # mph
    if u <= 1e-7:
        return 1.0
    return min(8.0, 0.936 * math.exp(0.1147 * u) + 0.461 * math.exp(-0.0692 * u) - 0.397)


def ellipse_rates(head: float, lwr: float) -> tuple[float, float, float]:
    """Return eccentricity, backing and flanking spread rates for an elliptical fire."""
    ecc = math.sqrt(lwr * lwr - 1) / lwr if lwr > 1 else 0.0
    back = head * (1 - ecc) / (1 + ecc)
    flank = (head + back) / (2 * lwr)
    return ecc, back, flank


def ros_in_direction(head: float, ecc: float, angle_from_head_deg: float) -> float:
    """Spread rate from the ignition point in a direction (Catchpole et al. 1982 polar ellipse form)."""
    return head * (1 - ecc) / (1 - ecc * math.cos(math.radians(angle_from_head_deg)))


# ---------------------------------------------------------------- public API (SI)
FT_MIN_TO_M_MIN = 0.3048
MPH_TO_FT_MIN = 88.0
KMH_TO_MPH = 0.621371


def surface_fire(fuel: int, moisture_pct: dict, wind_20ft_kmh: float, wind_from_deg: float,
                 slope_pct: float = 0.0, aspect_deg: float = 0.0, waf: float | None = None,
                 canopy_cover_pct: float = 0.0, canopy_height_m: float = 0.0, crown_ratio: float = 0.5,
                 wind_limit: bool = True) -> dict:
    """Point fire behaviour, BehavePlus-style. Wind is the 20-ft (6.1 m) open wind; aspect is the downslope
    direction (compass deg). Returns SI outputs."""
    fm = FUEL_MODELS[fuel]
    m = {k: moisture_pct[k] / 100.0 for k in ("1h", "10h", "100h", "herb", "woody")}
    base = rothermel_no_wind(fm, m)
    if not base["burnable"]:
        return {"burnable": False, "fuel": fm.code}
    if waf is None:
        sh = sheltered_waf(canopy_cover_pct / 100, canopy_height_m / 0.3048, crown_ratio)
        waf_used, waf_src = (sh, "sheltered by canopy") if sh is not None else (unsheltered_waf(fm.depth), "unsheltered fuel bed")
    else:
        waf_used, waf_src = waf, "user"
    mid = wind_20ft_kmh * KMH_TO_MPH * waf_used * MPH_TO_FT_MIN
    ws = wind_slope(base, mid, slope_pct / 100.0, (wind_from_deg + 180) % 360, (aspect_deg + 180) % 360, wind_limit)
    lwr = length_to_width(ws["u_eff"])
    ecc, back, flank = ellipse_rates(ws["ros"], lwr)
    t_res = 384.0 / base["sigma"]                                      # residence time, min
    hpa = base["ir"] * t_res                                           # Btu/ft2
    intensity = hpa * ws["ros"] / 60.0                                 # Btu/ft/s (Byram)
    flame = 0.45 * intensity ** 0.46 if intensity > 0 else 0.0         # ft (Byram 1959)
    return {
        "burnable": True, "fuel": fm.code, "fuel_name": fm.name,
        "ros_head_m_min": ws["ros"] * FT_MIN_TO_M_MIN, "ros_back_m_min": back * FT_MIN_TO_M_MIN,
        "ros_flank_m_min": flank * FT_MIN_TO_M_MIN, "ros_no_wind_m_min": base["r0"] * FT_MIN_TO_M_MIN,
        "dir_max_spread_deg": ws["dir"], "eccentricity": ecc, "length_to_width": lwr,
        "effective_wind_kmh": ws["u_eff"] / MPH_TO_FT_MIN / KMH_TO_MPH, "midflame_wind_kmh": mid / MPH_TO_FT_MIN / KMH_TO_MPH,
        "waf": waf_used, "waf_source": waf_src, "wind_limited": ws["wind_limited"],
        "reaction_intensity_kw_m2": base["ir"] * 0.18924,              # Btu/ft2/min -> kW/m2
        "heat_per_area_kj_m2": hpa * 11.3565,                          # Btu/ft2 -> kJ/m2
        "fireline_intensity_kw_m": intensity * 3.46414,                # Btu/ft/s -> kW/m
        "flame_length_m": flame * 0.3048, "residence_time_min": t_res,
        "live_mx_pct": base["mx_live"] * 100, "char_sav_ft": base["sigma"], "phi_w": ws["phi_w"], "phi_s": ws["phi_s"],
        "_base": base, "_ws": ws,
    }
