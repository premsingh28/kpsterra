// Satellite positions are computed in the browser with SGP4 (satellite.js) from orbital elements fetched by the backend.
import { API, fmt, getJSON } from './config.js';

const sats = [];           // {info, satrec, marker, el}

// Marker colour = primary fire/land sensor (not the track). Exported for the legend.
export const SENSORS = {
  VIIRS: { color: '#fb923c', sats: [37849, 43013, 54234], label: 'VIIRS: Suomi-NPP, NOAA-20, NOAA-21' },
  MODIS: { color: '#facc15', sats: [25994, 27424], label: 'MODIS: Terra, Aqua' },
  SLSTR: { color: '#22d3ee', sats: [41335, 43437], label: 'SLSTR: Sentinel-3A, Sentinel-3B' },
  OLI: { color: '#a78bfa', sats: [39084, 49260], label: 'OLI: Landsat 8, Landsat 9' },
};
const sensorOf = norad => Object.entries(SENSORS).find(([, s]) => s.sats.includes(norad))?.[0] ?? 'VIIRS';
const TRACK_AHEAD_MIN = 720;   // full 12-hour track for the selected satellite

// Sun elevation (deg) at a point: low-precision solar position, ample for a day/night flag.
export function sunElevation(date, lat, lon) {
  const d = (date - Date.UTC(2000, 0, 1, 12)) / 864e5;
  const g = (357.529 + 0.98560028 * d) * Math.PI / 180;
  const q = 280.459 + 0.98564736 * d;
  const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * Math.PI / 180;
  const e = (23.439 - 0.00000036 * d) * Math.PI / 180;
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const gmst = (18.697374558 + 24.06570982441908 * d) % 24 * 15 * Math.PI / 180;
  const ha = gmst + lon * Math.PI / 180 - ra;
  const la = lat * Math.PI / 180;
  return Math.asin(Math.sin(la) * Math.sin(dec) + Math.cos(la) * Math.cos(dec) * Math.cos(ha)) * 180 / Math.PI;
}
let selected = null;
let timer = null;
let filter = 'all';
let visible = true;

export function addSatLayers(map) {
  map.addSource('sat-track', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'sat-track', type: 'line', source: 'sat-track',
    paint: { 'line-color': '#38bdf8', 'line-width': 1.6, 'line-opacity': ['case', ['==', ['get', 'part'], 'past'], 0.35, 0.9],
      'line-dasharray': [2, 1.5] } });
}

export function position(satrec, date) {
  const pv = satellite.propagate(satrec, date);
  if (!pv.position) return null;
  const gd = satellite.eciToGeodetic(pv.position, satellite.gstime(date));
  const v = pv.velocity;
  return { lat: satellite.degreesLat(gd.latitude), lon: satellite.degreesLong(gd.longitude), alt: gd.height,
    speed: Math.hypot(v.x, v.y, v.z) };
}

export async function loadSatellites(map, onSelect) {
  const meta = document.getElementById('sat-meta');
  meta.textContent = 'Loading orbital elements…';
  try {
    const d = await getJSON(`${API}/api/satellites`);
    sats.forEach(s => s.marker.remove());
    sats.length = 0;
    for (const info of d.satellites) {
      const el = document.createElement('div');
      el.className = 'sat-marker';
      el.innerHTML = `<i></i><span>${info.name}</span>`;
      el.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;color:#bae6fd;text-shadow:0 0 3px #000';
      const sensor = sensorOf(info.norad_id);
      el.firstChild.style.cssText = `width:10px;height:10px;border-radius:50%;background:${SENSORS[sensor].color};box-shadow:0 0 8px ${SENSORS[sensor].color};border:1px solid #fff`;
      const s = { info, sensor, satrec: satellite.twoline2satrec(info.tle[0], info.tle[1]), el };
      s.marker = new maplibregl.Marker({ element: el, anchor: 'left', offset: [-5, 0] }).setLngLat([info.position.lon, info.position.lat]).addTo(map);
      el.addEventListener('click', ev => { ev.stopPropagation(); select(map, s, onSelect); });
      sats.push(s);
    }
    const ages = d.satellites.map(s => s.tle_age_hours);
    meta.innerHTML = `${d.satellites.length} satellites · orbital elements ${fmt(Math.min(...ages), 0)}–${fmt(Math.max(...ages), 0)} h old (${(d.sources || []).join(', ')})${d.satellites.some(s => s.tle_stale) ? ' <b style="color:#fbbf24">(cached: sources unreachable)</b>' : ''}<br>Positions are SGP4 estimates, not live telemetry.${d.errors.length ? `<br><span style="color:#f87171">Unavailable: ${d.errors.map(e => e.name).join(', ')}</span>` : ''}`;
    renderList(map, onSelect);
    clearInterval(timer);
    timer = setInterval(() => tick(map, onSelect), 1000);
    tick(map, onSelect);
  } catch (e) {
    meta.innerHTML = `<span style="color:#f87171">Satellite tracking unavailable: ${e.message}</span>`;
  }
}

function renderList(map, onSelect) {
  const ul = document.getElementById('sat-list');
  ul.innerHTML = '';
  for (const s of sats) {
    if (filter !== 'all' && s.info.type !== filter) continue;
    const li = document.createElement('li');
    li.innerHTML = `<span>${s.info.name}</span><small>${s.info.mission} · ${s.info.sensors[0]}</small>`;
    li.classList.toggle('sel', s === selected);
    li.onclick = () => select(map, s, onSelect, true);
    ul.appendChild(li);
  }
}

export function setFilter(map, f, onSelect) {
  filter = f;
  applyVisibility();
  renderList(map, onSelect);
}

export function setVisible(map, on) {
  visible = on;
  applyVisibility();
  map.setLayoutProperty('sat-track', 'visibility', on ? 'visible' : 'none');
}

function applyVisibility() {
  for (const s of sats) s.el.style.display = visible && (filter === 'all' || s.info.type === filter) ? 'flex' : 'none';
}

function select(map, s, onSelect, fly = false) {
  selected = s;
  drawTrack(map);
  renderList(map, onSelect);
  const p = position(s.satrec, new Date());
  if (fly && p) map.flyTo({ center: [p.lon, p.lat], zoom: Math.min(map.getZoom(), 3), speed: 0.8 });
  onSelect(s, p);
}

export const getSelected = () => selected;

function drawTrack(map) {
  if (!selected) return;
  const now = Date.now();
  const segs = { past: [[]], future: [[]] };
  let prev = null;
  for (let m = -50; m <= TRACK_AHEAD_MIN; m += 2) {
    const p = position(selected.satrec, new Date(now + m * 60000));
    if (!p) continue;
    const part = m <= 0 ? 'past' : 'future';
    const arr = segs[part];
    if (prev && Math.abs(p.lon - prev.lon) > 180) arr.push([]);       // split at antimeridian
    arr[arr.length - 1].push([p.lon, p.lat]);
    if (m === 0) segs.future[0].push([p.lon, p.lat]);
    prev = p;
  }
  const features = Object.entries(segs).map(([part, lines]) => ({ type: 'Feature', properties: { part },
    geometry: { type: 'MultiLineString', coordinates: lines.filter(l => l.length > 1) } }));
  map.getSource('sat-track').setData({ type: 'FeatureCollection', features });
}

let lastTrack = 0;
function tick(map, onSelect) {
  const now = new Date();
  for (const s of sats) {
    const p = position(s.satrec, now);
    if (p) {
      s.marker.setLngLat([p.lon, p.lat]);
      // Landsat OLI images in daylight only: fade it while its sub-satellite point is in darkness
      s.dark = sunElevation(now, p.lat, p.lon) < 0;
      s.el.style.opacity = s.sensor === 'OLI' && s.dark ? 0.4 : 1;
    }
    if (s === selected && p) onSelect(s, p, true);
  }
  if (selected && now - lastTrack > 30000) { drawTrack(map); lastTrack = +now; }
  document.getElementById('clock').textContent = now.toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
}

export function satInfoHTML(s, p) {
  const i = s.info;
  const age = (Date.now() - Date.parse(i.tle_epoch_utc)) / 3.6e6;
  const sunEl = p ? sunElevation(new Date(), p.lat, p.lon) : null;
  const light = sunEl == null ? '—' : sunEl >= 0 ? `Daylight (sun ${sunEl.toFixed(0)}° up)` :
    `Night (sun ${(-sunEl).toFixed(0)}° below horizon)${s.sensor === 'OLI' ? '. Landsat OLI images in daylight only' : '. Thermal fire detection works at night'}`;
  return `<p class="note">Estimated position from public orbital elements (SGP4). Not live telemetry; accuracy degrades with element age (typically ~1 km per day for LEO). Whether an instrument is actually acquiring data is not known.</p>
  <dl class="kv">
    <dt>Satellite</dt><dd>${i.name} (NORAD ${i.norad_id})</dd>
    <dt>Sensor colour</dt><dd><i class="sw" style="background:${SENSORS[s.sensor].color};border-radius:50%"></i> ${s.sensor}</dd>
    <dt>Below the satellite</dt><dd>${light}</dd>
    <dt>Mission</dt><dd>${i.mission}</dd>
    <dt>Instruments</dt><dd>${i.sensors.join(', ')}</dd>
    <dt>Latitude</dt><dd>${p ? p.lat.toFixed(3) + '°' : '—'}</dd>
    <dt>Longitude</dt><dd>${p ? p.lon.toFixed(3) + '°' : '—'}</dd>
    <dt>Altitude</dt><dd>${p ? fmt(p.alt, 1) + ' km' : '—'}</dd>
    <dt>Orbital speed</dt><dd>${p ? fmt(p.speed, 2) + ' km/s' : '—'}</dd>
    <dt>Elements epoch</dt><dd>${i.tle_epoch_utc.replace('T', ' ').replace('+00:00', '')} UTC</dd>
    <dt>Elements age</dt><dd>${fmt(age, 1)} h</dd>
    <dt>Source</dt><dd>${i.tle_source}${i.tle_stale ? ' (cached copy)' : ''}</dd>
  </dl>
  <p class="meta">Dashed line: ground track for the next 12 hours (faded = last 50 min).</p>`;
}
