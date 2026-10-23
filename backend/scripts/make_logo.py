"""Render the KPSTerra logo: a realistic Earth (NASA Blue Marble Next Generation, public domain) seen from
space over India, lit by the sun, with a thin atmosphere, India's real fire hotspots (MODIS 2001-2026
density, from frontend/data/grid_yearly.json), a procedural flame rising from central India, and a rendered
Earth-observation satellite on its orbit.

Usage: python scripts/make_logo.py
Outputs (frontend/assets/): kpsterra-logo.png (512, still), kpsterra-logo-192.png, favicon-64.png,
and layers for the animated web logo: kpsterra-globe.png, kpsterra-satellite.png, kpsterra-logo-geom.json
"""
import io
import json
from pathlib import Path

import httpx
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "backend" / "cache" / "BlueMarble_NextGeneration.jpg"
ASSETS = ROOT / "frontend" / "assets"
WMS = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
       "&LAYERS=BlueMarble_NextGeneration&CRS=EPSG:4326&BBOX=-90,-180,90,180&WIDTH=4096&HEIGHT=2048&FORMAT=image/jpeg")

S = 1536                      # render size (supersampled, then downscaled)
R = 0.43 * S                  # globe radius in pixels
LON0, LAT0 = 80.0, 17.0       # view centre: India
SUN = np.array([-0.55, 0.45, 0.70])   # light from upper left, in view space (x right, y up, z to viewer)


def texture() -> np.ndarray:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(httpx.get(WMS, timeout=180).content)
    return np.asarray(Image.open(CACHE).convert("RGB"), dtype=np.float32) / 255.0


def render():
    tex = texture()
    th, tw = tex.shape[:2]
    c = (S - 1) / 2
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    x = (xx - c) / R
    y = (c - yy) / R
    rho = np.sqrt(x * x + y * y)
    inside = rho <= 1.0
    z = np.sqrt(np.clip(1 - rho ** 2, 0, 1))

    # inverse orthographic projection
    p0 = np.radians(LAT0)
    lat = np.degrees(np.arcsin(np.clip(z * np.sin(p0) + y * np.cos(p0), -1, 1)))
    lon = LON0 + np.degrees(np.arctan2(x, z * np.cos(p0) - y * np.sin(p0)))
    lon = (lon + 180) % 360 - 180
    rows = (90 - lat) / 180 * (th - 1)
    cols = (lon + 180) / 360 * (tw - 1)
    img = np.stack([map_coordinates(tex[..., k], [rows, cols], order=1, mode="wrap") for k in range(3)], -1)

    # a touch more contrast/saturation (Blue Marble is quite flat), then sunlight
    lum = img.mean(-1, keepdims=True)
    img = np.clip(lum + (img - lum) * 1.25, 0, 1) ** 0.95
    sun = SUN / np.linalg.norm(SUN)
    ndotl = np.clip(x * sun[0] + y * sun[1] + z * sun[2], 0, 1)
    light = 0.32 + 0.85 * ndotl ** 0.75
    img = img * light[..., None]
    # specular glint on the oceans (blue-dominant pixels)
    half = sun + np.array([0, 0, 1.0]); half /= np.linalg.norm(half)
    spec = np.clip(x * half[0] + y * half[1] + z * half[2], 0, 1) ** 60
    ocean = np.clip((img[..., 2] - img[..., 0]) * 4, 0, 1)
    img += (spec * ocean * 0.35)[..., None]

    # real fire hotspots: MODIS 2001-2026 mean detections per 0.25 deg cell
    grid = json.loads((ROOT / "frontend" / "data" / "grid_yearly.json").read_text())
    cells = np.array([[cl[0] + 0.125, cl[1] + 0.125, np.mean(cl[3:])] for cl in grid["cells"]])
    cells = cells[cells[:, 2] >= 18]                    # the most fire-active cells only
    lam = np.radians(cells[:, 0] - LON0)
    phi = np.radians(cells[:, 1])
    cosc = np.sin(p0) * np.sin(phi) + np.cos(p0) * np.cos(phi) * np.cos(lam)
    fx = np.cos(phi) * np.sin(lam)
    fy = np.cos(p0) * np.sin(phi) - np.sin(p0) * np.cos(phi) * np.cos(lam)
    vis = cosc > 0.05
    px = np.round(c + fx[vis] * R).astype(int)
    py = np.round(c - fy[vis] * R).astype(int)
    w = np.log1p(cells[vis, 2]) / np.log1p(cells[:, 2].max())
    heat = np.zeros((S, S), np.float32)
    np.add.at(heat, (py, px), w)
    core = gaussian_filter(heat, 1.1) * 5
    glow = gaussian_filter(heat, 3.5) * 10
    fire = np.clip(core, 0, 1)[..., None] * np.array([1.0, 0.80, 0.42]) + \
        np.clip(glow, 0, 1)[..., None] * np.array([1.0, 0.35, 0.05]) * 0.8
    img = np.clip(img + fire * inside[..., None], 0, 1)

    # limb: slight darkening and blue scattering near the edge
    limb = np.clip(rho, 0, 1) ** 8
    img = img * (1 - 0.25 * limb[..., None]) + np.array([0.35, 0.6, 1.0]) * (0.35 * limb * (0.3 + 0.7 * ndotl))[..., None]

    # atmosphere halo outside the disc, brighter on the sunlit side
    lit_side = np.clip((x * sun[0] + y * sun[1]) / np.maximum(rho, 1e-6) * 0.5 + 0.5, 0, 1)
    halo = np.exp(-np.clip(rho - 1, 0, None) * 28) * (rho > 1) * (0.25 + 0.75 * lit_side)
    edge = np.clip((1 - rho) * R, 0, 1)                 # anti-aliased disc edge
    alpha = np.clip(edge + halo * 0.85, 0, 1)
    halo_rgb = np.array([0.45, 0.72, 1.0])
    rgb = np.where(inside[..., None], img, halo_rgb * np.ones_like(img))
    rgba = np.dstack([np.clip(rgb, 0, 1), alpha])

    # realistic flame rising from central India
    fl = np.radians(79.0 - LON0), np.radians(22.5)
    bx = c + np.cos(fl[1]) * np.sin(fl[0]) * R
    by = c - (np.cos(p0) * np.sin(fl[1]) - np.sin(p0) * np.cos(fl[1]) * np.cos(fl[0])) * R
    return composite_flame(rgba, bx, by, height=0.62 * R, width=0.42 * R)


# ---------------------------------------------------------------- fire
def _noise(shape, sigma, rng):
    n = gaussian_filter(rng.standard_normal(shape), sigma)
    return n / (np.abs(n).max() + 1e-9)


def flame_sprite(h: int, w: int, seed: int = 7) -> np.ndarray:
    """Procedural turbulent flame, RGBA float. Colour from a black-body-like ramp (dark red -> white-hot core)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    y = 1 - yy / (h - 1)                       # 0 bottom -> 1 top
    x = (xx / (w - 1)) * 2 - 1                 # -1 .. 1
    n1 = _noise((h, w), h * 0.06, rng)
    n2 = _noise((h, w), h * 0.022, rng)
    n3 = _noise((h, w), h * 0.012, rng)
    xd = x + 0.30 * n1 * y ** 1.1 + 0.10 * n2 * y        # turbulence grows with height
    width = 0.62 * (1 - y) ** 0.75 + 0.015
    body = np.exp(-(xd / width) ** 2)
    base = np.clip(y / 0.08, 0, 1) ** 0.6                # soft bottom
    top = np.clip((1 - y) / 0.85, 0, 1) ** 0.55
    tongues = np.clip(0.75 + 0.55 * n3 + 0.25 * n2, 0, 1.2)
    T = np.clip(body * base * top * tongues, 0, 1)
    core = np.exp(-(xd / (width * 0.42)) ** 2) * np.clip(1 - y / 0.55, 0, 1) * base
    T = np.clip(T + 0.55 * core, 0, 1)
    stops = np.array([0.0, 0.18, 0.38, 0.6, 0.8, 1.0])
    cols = np.array([[0.20, 0.0, 0.0], [0.55, 0.04, 0.0], [0.90, 0.20, 0.02],
                     [1.0, 0.50, 0.06], [1.0, 0.80, 0.32], [1.0, 0.97, 0.86]])
    rgb = np.stack([np.interp(T, stops, cols[:, k]) for k in range(3)], -1)
    alpha = np.clip(T * 1.9, 0, 1) ** 1.2
    return np.dstack([rgb, alpha])


def composite_flame(rgba, bx, by, height, width):
    h, w = int(height), int(width)
    sp = flame_sprite(h, w)
    out = rgba.copy()
    x0, y0 = int(bx - w / 2), int(by - h * 0.93)         # base of the flame sits on India
    region = out[y0:y0 + h, x0:x0 + w]
    a = sp[..., 3:4]
    region[..., :3] = region[..., :3] * (1 - a) + sp[..., :3] * a
    region[..., 3:4] = np.maximum(region[..., 3:4], a)
    # warm glow around the fire, added to the globe
    glow = np.zeros(out.shape[:2], np.float32)
    glow[y0:y0 + h, x0:x0 + w] = sp[..., 3]
    glow = gaussian_filter(glow, height * 0.09)
    out[..., :3] = np.clip(out[..., :3] + glow[..., None] * np.array([1.0, 0.45, 0.1]) * 0.55, 0, 1)
    return out


# ---------------------------------------------------------------- satellite
def satellite_sprite(n: int = 192) -> Image.Image:
    """Small rendered Earth-observation satellite: gold-foil bus, two blue solar wings, antenna."""
    from PIL import ImageDraw, ImageFilter
    k = 4                                        # supersampling
    W = n * k
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = W / 2, W / 2
    # solar wings (slight perspective: far edge narrower)
    def wing(sign):
        x_in, x_out = cx + sign * W * 0.10, cx + sign * W * 0.47
        poly = [(x_in, cy - W * 0.085), (x_out, cy - W * 0.07), (x_out, cy + W * 0.07), (x_in, cy + W * 0.085)]
        d.polygon(poly, fill=(14, 34, 84, 255), outline=(190, 200, 215, 255), width=k * 2)
        for i in range(1, 6):                      # cell grid
            t = i / 6
            xa = x_in + (x_out - x_in) * t
            hh = W * (0.085 - 0.015 * t)
            d.line([(xa, cy - hh), (xa, cy + hh)], fill=(70, 110, 170, 255), width=k)
        d.line([(x_in, cy), (x_out, cy)], fill=(70, 110, 170, 255), width=k)
    wing(-1)
    wing(1)
    # boom
    d.line([(cx - W * 0.11, cy), (cx + W * 0.11, cy)], fill=(170, 175, 185, 255), width=k * 3)
    # bus: front face, top and side faces (gold multilayer insulation)
    f = [(cx - W * 0.08, cy - W * 0.07), (cx + W * 0.06, cy - W * 0.07), (cx + W * 0.06, cy + W * 0.09), (cx - W * 0.08, cy + W * 0.09)]
    top = [(cx - W * 0.08, cy - W * 0.07), (cx - W * 0.04, cy - W * 0.11), (cx + W * 0.10, cy - W * 0.11), (cx + W * 0.06, cy - W * 0.07)]
    side = [(cx + W * 0.06, cy - W * 0.07), (cx + W * 0.10, cy - W * 0.11), (cx + W * 0.10, cy + W * 0.05), (cx + W * 0.06, cy + W * 0.09)]
    d.polygon(side, fill=(150, 105, 25, 255))
    d.polygon(top, fill=(240, 205, 110, 255))
    d.polygon(f, fill=(212, 160, 45, 255))
    # antenna dish
    d.ellipse([cx - W * 0.03, cy + W * 0.09, cx + W * 0.03, cy + W * 0.13], fill=(225, 228, 232, 255))
    im = im.resize((n, n), Image.LANCZOS)
    # foil crinkle + panel sheen
    a = np.asarray(im, dtype=np.float32) / 255
    rng = np.random.default_rng(3)
    crinkle = gaussian_filter(rng.standard_normal(a.shape[:2]), 0.8) * 0.18
    gold = (a[..., 0] > a[..., 2] + 0.15)
    a[..., :3] += (crinkle * gold)[..., None]
    yy, xx = np.mgrid[0:n, 0:n]
    sheen = np.clip(1 - np.abs((xx - yy) / n - 0.05) * 3.2, 0, 1) * 0.35
    blue = a[..., 2] > a[..., 0] + 0.1
    a[..., :3] += (sheen * blue)[..., None] * np.array([0.5, 0.7, 1.0])
    out = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "RGBA").rotate(18, resample=Image.BICUBIC)
    return out


# ---------------------------------------------------------------- composite (orbit + satellite)
CANVAS = 1.32            # canvas side relative to the globe render
ORBIT = dict(rx=0.47, ry=0.13, tilt=-18.0)   # as fractions of the canvas side; tilt in degrees


def orbit_points(C, t):
    a, b, th = ORBIT["rx"] * C, ORBIT["ry"] * C, np.radians(ORBIT["tilt"])
    x, y = a * np.cos(t), b * np.sin(t)
    return C / 2 + x * np.cos(th) - y * np.sin(th), C / 2 + x * np.sin(th) + y * np.cos(th)


def draw_ring(C, t0, t1, alpha, width):
    from PIL import ImageDraw
    k = 2
    layer = Image.new("RGBA", (C * k, C * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    t = np.linspace(t0, t1, 400)
    xs, ys = orbit_points(C, t)
    d.line(list(zip(xs * k, ys * k)), fill=(170, 220, 255, int(255 * alpha)), width=max(1, int(width * k)))
    return layer.resize((C, C), Image.LANCZOS)


def build():
    globe = render()
    g = Image.fromarray((np.clip(globe, 0, 1) * 255).astype(np.uint8), "RGBA")
    C = int(S * CANVAS)
    base = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    base.alpha_composite(g, ((C - S) // 2, (C - S) // 2))
    sat = satellite_sprite(int(C * 0.2))
    ASSETS.mkdir(parents=True, exist_ok=True)

    # layers for the animated web logo (the page draws the orbit and moves the satellite)
    base.resize((512, 512), Image.LANCZOS).save(ASSETS / "kpsterra-globe.png", optimize=True)
    sat.resize((128, 128), Image.LANCZOS).save(ASSETS / "kpsterra-satellite.png", optimize=True)

    # still composite: back half of the ring, globe, front half, satellite in front
    still = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    still.alpha_composite(draw_ring(C, np.pi, 2 * np.pi, 0.22, C * 0.0035))
    still.alpha_composite(base)
    still.alpha_composite(draw_ring(C, 0, np.pi, 0.55, C * 0.0045))
    sx, sy = orbit_points(C, np.radians(35))
    still.alpha_composite(sat, (int(sx - sat.width / 2), int(sy - sat.height / 2)))
    for size, name in ((512, "kpsterra-logo.png"), (192, "kpsterra-logo-192.png")):
        still.resize((size, size), Image.LANCZOS).save(ASSETS / name, optimize=True)
        print("wrote", ASSETS / name)
    # favicon: globe + fire only, cropped tight, so it stays readable at 16-32 px
    pad = int(S * 0.04)
    g.crop((pad, pad, S - pad, S - pad)).resize((64, 64), Image.LANCZOS).save(ASSETS / "favicon-64.png", optimize=True)
    (ASSETS / "kpsterra-logo-geom.json").write_text(json.dumps({**ORBIT, "satellite_size": 0.2}))


if __name__ == "__main__":
    build()
