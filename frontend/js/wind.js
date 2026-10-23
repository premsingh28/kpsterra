// Animated wind particles from the GFS 10 m wind grid, drawn on a canvas above the map.
import { API, getJSON } from './config.js';

const N_PARTICLES = 4000;
const MAX_AGE = 90;
let grid = null, parts = [], running = false, raf = 0, map = null, canvas = null, ctx = null;

export async function loadWind() {
  grid = await getJSON(`${API}/api/layers/wind`, { timeout: 90000 });
  return grid;
}

function sample(lon, lat) {
  const g = grid;
  const x = ((lon - g.lon0) % 360 + 360) % 360 / g.dlon;
  const y = (lat - g.lat0) / g.dlat;
  if (y < 0 || y > g.ny - 1) return null;
  const x0 = Math.floor(x), y0 = Math.floor(y), x1 = (x0 + 1) % g.nx, y1 = Math.min(y0 + 1, g.ny - 1);
  const fx = x - x0, fy = y - y0;
  const at = (arr, i, j) => arr[j * g.nx + i] * g.scale;
  const bil = arr => (at(arr, x0, y0) * (1 - fx) + at(arr, x1, y0) * fx) * (1 - fy) + (at(arr, x0, y1) * (1 - fx) + at(arr, x1, y1) * fx) * fy;
  return [bil(g.u), bil(g.v)];
}

// 10 m wind at a point from the loaded GFS grid: speed (m/s) and the compass direction it blows FROM.
export function windAt(lon, lat) {
  if (!grid) return null;
  const uv = sample(lon, lat);
  if (!uv) return null;
  const [u, v] = uv;
  return { speed_ms: Math.hypot(u, v), from_deg: (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360,
    valid_time: grid.valid_time_utc, source: grid.source };
}

function spawn() {
  const b = map.getBounds();
  const zoomedOut = map.getZoom() < 3;
  const west = zoomedOut ? -180 : b.getWest(), east = zoomedOut ? 180 : b.getEast();
  const south = Math.max(-80, zoomedOut ? -80 : b.getSouth()), north = Math.min(80, zoomedOut ? 80 : b.getNorth());
  return { lon: west + Math.random() * (east - west), lat: south + Math.random() * (north - south), age: Math.floor(Math.random() * MAX_AGE) };
}

function visible(lngLat) {
  const t = map.transform;
  return typeof t.isLocationOccluded === 'function' ? !t.isLocationOccluded(lngLat) : true;
}

function frame() {
  if (!running) return;
  const w = canvas.width, h = canvas.height, dpr = devicePixelRatio || 1;
  ctx.globalCompositeOperation = 'destination-in';
  ctx.fillStyle = 'rgba(0,0,0,0.92)';
  ctx.fillRect(0, 0, w, h);
  ctx.globalCompositeOperation = 'source-over';
  ctx.lineWidth = 1.1 * dpr;
  // step size in degrees per frame, shrinking as the user zooms in
  const k = 0.0045 * Math.pow(2, 3 - map.getZoom());
  for (const p of parts) {
    const uv = p.age < MAX_AGE ? sample(p.lon, p.lat) : null;
    if (!uv) { Object.assign(p, spawn(), { age: 0 }); continue; }
    const speed = Math.hypot(uv[0], uv[1]);
    const lon2 = p.lon + uv[0] * k / Math.max(0.2, Math.cos(p.lat * Math.PI / 180));
    const lat2 = p.lat + uv[1] * k;
    if (Math.abs(lat2) > 85) { Object.assign(p, spawn(), { age: 0 }); continue; }
    const a = { lng: p.lon, lat: p.lat }, b = { lng: lon2, lat: lat2 };
    if (visible(a) && visible(b) && Math.abs(lon2 - p.lon) < 10) {
      const s1 = map.project(a), s2 = map.project(b);
      ctx.strokeStyle = speed > 12 ? 'rgba(186,230,253,0.95)' : speed > 6 ? 'rgba(224,242,254,0.8)' : 'rgba(255,255,255,0.55)';
      ctx.beginPath();
      ctx.moveTo(s1.x * dpr, s1.y * dpr);
      ctx.lineTo(s2.x * dpr, s2.y * dpr);
      ctx.stroke();
    }
    p.lon = ((lon2 + 540) % 360) - 180;
    p.lat = lat2;
    p.age++;
  }
  raf = requestAnimationFrame(frame);
}

function resize() {
  const dpr = devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
}

const clear = () => ctx?.clearRect(0, 0, canvas.width, canvas.height);

export function startWind(m) {
  map = m;
  canvas = document.getElementById('wind-canvas');
  ctx = canvas.getContext('2d');
  resize();
  if (!startWind.bound) {
    window.addEventListener('resize', resize);
    map.on('movestart', clear);
    map.on('move', clear);
    map.on('moveend', () => running && (parts = parts.map(() => spawn())));
    startWind.bound = true;
  }
  parts = Array.from({ length: N_PARTICLES }, spawn);
  running = true;
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(frame);
}

export function stopWind() {
  running = false;
  cancelAnimationFrame(raf);
  clear();
}
