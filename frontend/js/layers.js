// Context overlays: NASA GIBS imagery, GDACS alerts and cyclone tracks, official wildfire incidents.
import { API, fmt, getJSON, toast } from './config.js';
import { gibsURL } from './map.js';

const EMPTY = { type: 'FeatureCollection', features: [] };
const $ = id => document.getElementById(id);
let gibsTimes = null;
let opacity = 0.7;

export const STATUS = {
  uncontained: { color: '#ff3b30', label: 'Out of control / not yet contained' },
  held: { color: '#ffcc00', label: 'Being held / under control' },
  prescribed: { color: '#34c759', label: 'Prescribed burn' },
  out: { color: '#8e8e93', label: 'Out' },
};
const ALERT = { Green: '#22c55e', Orange: '#f97316', Red: '#ef4444' };
const GDACS_TYPES = { TC: 'Tropical cyclone', EQ: 'Earthquake', FL: 'Flood', VO: 'Volcano', DR: 'Drought', WF: 'Wildfire' };

export async function loadGibsTimes() {
  try {
    gibsTimes = (await getJSON(`${API}/api/layers/gibs-times`)).layers;
  } catch {
    gibsTimes = null;
  }
  document.querySelectorAll('[data-meta]').forEach(el => {
    const t = gibsTimes?.[el.dataset.meta]?.time;
    el.textContent = t ? `Latest: ${t.replace('T', ' ').replace('Z', ' UTC')} · NASA GIBS` : 'NASA GIBS (time unknown: backend offline)';
  });
  return gibsTimes;
}

export function gibsTime(layer) { return gibsTimes?.[layer]?.time; }

export function toggleGibs(map, layer, on) {
  const id = `gibs-${layer}`;
  if (on && !map.getLayer(id)) {
    const info = gibsTimes?.[layer] ?? { time: 'default', matrix: layer.startsWith('Himawari') || layer.startsWith('OMPS') ? 'GoogleMapsCompatible_Level6' : 'GoogleMapsCompatible_Level7' };
    const maxzoom = +(info.matrix.match(/Level(\d+)/)?.[1] ?? 7);
    map.addSource(id, { type: 'raster', tiles: [gibsURL(layer, info.time, info.matrix)], tileSize: 256, maxzoom, attribution: 'NASA GIBS' });
    map.addLayer({ id, type: 'raster', source: id, paint: { 'raster-opacity': opacity, 'raster-fade-duration': 0 } }, 'states-fill');
  }
  if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
}

export function setImageryOpacity(map, v) {
  opacity = v;
  for (const l of map.getStyle().layers) if (l.id.startsWith('gibs-')) map.setPaintProperty(l.id, 'raster-opacity', v);
}

// ---------- GDACS ----------
// Icon per hazard type: shape outlined in the alert colour (drawn on a canvas; no external sprites).
const GLYPH = { EQ: 'EQ', FL: 'FL', TC: 'TC', VO: 'VO', DR: 'DR', WF: 'WF' };
export function gdacsIcon(type, alert, size = 44) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  const r = size / 2 - 3;
  g.translate(size / 2, size / 2);
  g.beginPath();
  if (type === 'TC') {                 // cyclone: circle with two spiral arms
    g.arc(0, 0, r * 0.62, 0, 2 * Math.PI);
  } else if (type === 'EQ') {          // earthquake: diamond
    g.moveTo(0, -r); g.lineTo(r, 0); g.lineTo(0, r); g.lineTo(-r, 0); g.closePath();
  } else if (type === 'VO') {          // volcano: triangle
    g.moveTo(0, -r); g.lineTo(r, r * 0.8); g.lineTo(-r, r * 0.8); g.closePath();
  } else {
    g.arc(0, 0, r, 0, 2 * Math.PI);
  }
  g.fillStyle = '#0f172a';
  g.fill();
  g.lineWidth = 4;
  g.strokeStyle = ALERT[alert];
  g.stroke();
  if (type === 'TC') {
    g.beginPath(); g.arc(-r * 0.3, -r * 0.62, r * 0.55, Math.PI * 0.1, Math.PI * 0.9, true); g.stroke();
    g.beginPath(); g.arc(r * 0.3, r * 0.62, r * 0.55, Math.PI * 1.1, Math.PI * 1.9, true); g.stroke();
  }
  g.fillStyle = '#fff';
  g.font = `700 ${size * 0.3}px Inter, sans-serif`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(GLYPH[type], 0, type === 'VO' ? r * 0.25 : 1);
  return g.getImageData(0, 0, size, size);
}
let gdacsLoaded = false;
export function addHazardLayers(map) {
  map.addSource('gdacs', { type: 'geojson', data: EMPTY });
  map.addSource('tc', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'tc', type: 'line', source: 'tc', layout: { visibility: 'none', 'line-cap': 'round' },
    paint: { 'line-color': ['match', ['get', 'alert'], 'Red', ALERT.Red, 'Orange', ALERT.Orange, '#7dd3fc'], 'line-width': 2.2, 'line-opacity': 0.9 } });
  for (const t of Object.keys(GDACS_TYPES)) for (const a of Object.keys(ALERT)) {
    if (!map.hasImage(`gd-${t}-${a}`)) map.addImage(`gd-${t}-${a}`, gdacsIcon(t, a), { pixelRatio: 2 });
  }
  map.addLayer({ id: 'gdacs', type: 'symbol', source: 'gdacs', layout: { visibility: 'none',
    'icon-image': ['concat', 'gd-', ['get', 'type'], '-', ['get', 'alert']],
    'icon-size': ['match', ['get', 'alert'], 'Red', 1.15, 'Orange', 1, 0.85], 'icon-allow-overlap': true } });
  map.on('click', 'gdacs', e => {
    const p = e.features[0].properties;
    new maplibregl.Popup({ maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(`<b>${p.name}</b><dl class="kv">
      <dt>Type</dt><dd>${GDACS_TYPES[p.type] ?? p.type}</dd><dt>Alert level</dt><dd style="color:${ALERT[p.alert] ?? '#fff'}">${p.alert}</dd>
      <dt>Country</dt><dd>${p.country || '—'}</dd><dt>From</dt><dd>${(p.from || '').slice(0, 16).replace('T', ' ')}</dd><dt>To</dt><dd>${(p.to || '').slice(0, 16).replace('T', ' ')}</dd>
      ${p.severity ? `<dt>Severity</dt><dd>${p.severity}</dd>` : ''}</dl>${p.url && p.url !== 'null' ? `<a href="${p.url}" target="_blank" rel="noopener">GDACS report ↗</a>` : ''}`).addTo(map);
  });
  map.on('mouseenter', 'gdacs', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseleave', 'gdacs', () => (map.getCanvas().style.cursor = ''));
}

export async function toggleHazard(map, which, on) {
  if (on && !gdacsLoaded) {
    $('meta-gdacs').textContent = 'Loading GDACS…';
    try {
      const d = await getJSON(`${API}/api/layers/gdacs`);
      map.getSource('gdacs').setData(d.events);
      map.getSource('tc').setData(d.tc_tracks);
      gdacsLoaded = true;
      $('meta-gdacs').textContent = `${d.events.features.length} current events · GDACS · retrieved ${d.retrieved_utc.slice(11, 16)} UTC${d.stale ? ' (cached)' : ''}`;
    } catch (e) {
      $('meta-gdacs').innerHTML = `<span style="color:#f87171">GDACS unavailable: ${e.message}</span>`;
      toast(`GDACS unavailable: ${e.message}`, true);
    }
  }
  map.setLayoutProperty(which, 'visibility', on ? 'visible' : 'none');
}

// ---------- official incidents ----------
const incLoaded = {};
export function addIncidentLayers(map) {
  for (const r of ['us', 'canada']) {
    map.addSource(`inc-${r}`, { type: 'geojson', data: EMPTY });
    map.addLayer({ id: `inc-${r}`, type: 'circle', source: `inc-${r}`, layout: { visibility: 'none' }, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3.5, 7, 7],
      'circle-color': ['match', ['get', 'status'], ...Object.entries(STATUS).flatMap(([k, v]) => [k, v.color]), '#ff3b30'],
      'circle-stroke-color': '#000', 'circle-stroke-width': 0.8 } });
    map.on('click', `inc-${r}`, e => {
      const p = e.features[0].properties;
      const size = p.acres != null && p.acres !== 'null' ? `${fmt(+p.acres, 1)} acres` : p.hectares != null && p.hectares !== 'null' ? `${fmt(+p.hectares, 1)} ha` : '—';
      new maplibregl.Popup({ maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(`<b>${p.name || 'Unnamed incident'}</b><dl class="kv">
        <dt>Official status</dt><dd style="color:${STATUS[p.status]?.color}">${STATUS[p.status]?.label ?? p.status}</dd>
        <dt>Size</dt><dd>${size}</dd>${p.contained_pct != null && p.contained_pct !== 'null' ? `<dt>Contained</dt><dd>${p.contained_pct}%</dd>` : ''}
        ${p.discovered && p.discovered !== 'null' ? `<dt>Discovered</dt><dd>${p.discovered} UTC</dd>` : ''}<dt>Updated</dt><dd>${p.updated ?? '—'}</dd></dl>
        <small class="muted">Agency-reported incident (${r === 'us' ? 'NIFC WFIGS' : 'CWFIS'}).</small>`).addTo(map);
    });
  }
}

export async function toggleIncidents(map, region, on) {
  const meta = $(region === 'us' ? 'meta-inc-us' : 'meta-inc-ca');
  if (on && !incLoaded[region]) {
    meta.textContent = 'Loading…';
    try {
      const d = await getJSON(`${API}/api/layers/incidents?region=${region}`);
      map.getSource(`inc-${region}`).setData(d.geojson);
      incLoaded[region] = true;
      const counts = {};
      d.geojson.features.forEach(f => (counts[f.properties.status] = (counts[f.properties.status] ?? 0) + 1));
      meta.textContent = `${fmt(d.geojson.features.length)} incidents (${Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(', ')}) · ${d.source} · ${d.retrieved_utc.slice(11, 16)} UTC`;
    } catch (e) {
      meta.innerHTML = `<span style="color:#f87171">Unavailable: ${e.message}</span>`;
    }
  }
  map.setLayoutProperty(`inc-${region}`, 'visibility', on ? 'visible' : 'none');
}
