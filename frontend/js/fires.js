import { ACTIVITY_COLORS, API, CLUSTER_ACTIVITY, FRP_STEPS, download, fmt, getJSON, toast } from './config.js';
import { setVis } from './map.js';

const EMPTY = { type: 'FeatureCollection', features: [] };
const POINT_LAYERS = ['fires-glow', 'fires-pt'];
const HEAT_LAYERS = ['fires-heat'];
const CLUSTER_LAYERS = ['fires-cl', 'fires-cl-pt'];

export const state = { all: [], shown: EMPTY, meta: null, tMin: 0, tMax: 0, tCur: 0, style: 'points', on: true };

export function addFireLayers(map) {
  map.addSource('fires', { type: 'geojson', data: EMPTY });
  map.addSource('fires-c', { type: 'geojson', data: EMPTY, cluster: true, clusterRadius: 40, clusterMaxZoom: 9,
    clusterProperties: { frpmax: ['max', ['coalesce', ['get', 'frp'], 0]] } });

  const age = ['interpolate', ['linear'], ['get', 'age_h'], 0, 1.5, 24, 1, 120, 0.55];
  const r = base => ['interpolate', ['linear'], ['zoom'], 2, ['*', base[0], age], 6, ['*', base[1], age], 11, ['*', base[2], age]];
  map.addLayer({ id: 'fires-heat', type: 'heatmap', source: 'fires', layout: { visibility: 'none' }, paint: {
    'heatmap-weight': ['interpolate', ['linear'], ['coalesce', ['get', 'frp'], 1], 0, 0.2, 50, 1],
    'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 18],
    'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.2, '#7a1b0c', 0.45, '#e8233a', 0.7, '#ff8c42', 1, '#fff3b0'],
    'heatmap-opacity': 0.9 } });
  map.addLayer({ id: 'fires-glow', type: 'circle', source: 'fires', paint: {
    'circle-radius': r([5, 9, 16]), 'circle-color': ['step', ['coalesce', ['get', 'frp'], 0], ...FRP_STEPS],
    'circle-blur': 1, 'circle-opacity': ['interpolate', ['linear'], ['get', 'age_h'], 0, 0.55, 120, 0.08] } });
  map.addLayer({ id: 'fires-pt', type: 'circle', source: 'fires', paint: {
    'circle-radius': r([1.6, 3, 6]), 'circle-color': ['step', ['coalesce', ['get', 'frp'], 0], ...FRP_STEPS],
    'circle-opacity': ['interpolate', ['linear'], ['get', 'age_h'], 0, 1, 120, 0.35],
    'circle-stroke-width': ['case', ['<', ['get', 'age_h'], 3], 0.8, 0], 'circle-stroke-color': '#fff' } });
  map.addLayer({ id: 'fires-cl', type: 'circle', source: 'fires-c', filter: ['has', 'point_count'], layout: { visibility: 'none' }, paint: {
    'circle-radius': ['interpolate', ['linear'], ['get', 'point_count'], 2, 8, 100, 18, 2000, 34],
    'circle-color': ['step', ['get', 'point_count'], ACTIVITY_COLORS.low, CLUSTER_ACTIVITY.medium, ACTIVITY_COLORS.medium, CLUSTER_ACTIVITY.high, ACTIVITY_COLORS.high],
    'circle-opacity': 0.8,
    'circle-stroke-width': 1, 'circle-stroke-color': 'rgba(255,255,255,.6)' } });
  map.addLayer({ id: 'fires-cl-pt', type: 'circle', source: 'fires-c', filter: ['!', ['has', 'point_count']], layout: { visibility: 'none' }, paint: {
    'circle-radius': 3, 'circle-color': ['step', ['coalesce', ['get', 'frp'], 0], ...FRP_STEPS] } });

  map.on('click', 'fires-cl', e => {
    const f = e.features[0];
    new maplibregl.Popup({ closeButton: false }).setLngLat(e.lngLat)
      .setHTML(`<b>${fmt(f.properties.point_count)}</b> detections grouped for display (${f.properties.point_count >= CLUSTER_ACTIVITY.high ? 'high' : f.properties.point_count >= CLUSTER_ACTIVITY.medium ? 'medium' : 'low'} activity)<br>max FRP ${fmt(f.properties.frpmax, 1)} MW<br><small class="muted">A display cluster, not a fire event. Zoom in to see detections.</small>`).addTo(map);
  });
  for (const id of ['fires-pt', 'fires-cl', 'fires-cl-pt']) {
    map.on('mouseenter', id, () => (map.getCanvas().style.cursor = 'pointer'));
    map.on('mouseleave', id, () => (map.getCanvas().style.cursor = ''));
  }
}

export function popupHTML(p, lngLat) {
  const t = new Date(p.t);
  const ist = t.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' });
  return `<b style="color:#ffb08a">Satellite fire detection</b>
  <dl class="kv">
    <dt>Acquired (UTC)</dt><dd>${p.t.slice(0, 16).replace('T', ' ')}</dd>
    <dt>Acquired (IST)</dt><dd>${ist}</dd>
    <dt>Satellite / sensor</dt><dd>${p.sat} · ${p.inst}</dd>
    <dt>FRP</dt><dd>${p.frp == null ? '—' : fmt(p.frp, 1) + ' MW'}</dd>
    <dt>Confidence</dt><dd>${p.conf} (${p.cc})</dd>
    <dt>Brightness temp.</dt><dd>${fmt(p.bt, 1)} K</dd>
    <dt>Pixel scan × track</dt><dd>${p.scan} × ${p.track} km</dd>
    <dt>Day / night</dt><dd>${p.dn === 'D' ? 'Day' : 'Night'}</dd>
    <dt>Location</dt><dd>${lngLat[1].toFixed(4)}, ${lngLat[0].toFixed(4)}</dd>
    <dt>Product version</dt><dd>${p.ver}</dd>
  </dl><small class="muted">A thermal anomaly in one satellite pixel; not a verified fire incident.</small>`;
}

export async function loadFires(map, { source, days, region }) {
  const meta = document.getElementById('fire-meta');
  meta.textContent = 'Loading NASA FIRMS…';
  try {
    const d = await getJSON(`${API}/api/fires/live?source=${source}&days=${days}&region=${region}`, { timeout: 120000 });
    state.all = d.geojson.features;
    state.meta = d;
    const ts = state.all.map(f => Date.parse(f.properties.t));
    state.tMin = ts.length ? Math.min(...ts) : Date.now();
    state.tMax = ts.length ? Math.max(...ts) : Date.now();
    state.tCur = state.tMax;
    const latest = ts.length ? new Date(state.tMax).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '—';
    meta.innerHTML = `${fmt(d.count)} detections · ${d.source_label}<br>Latest acquisition: ${latest}<br>Retrieved ${d.retrieved_utc.replace('T', ' ').slice(0, 16)} UTC${d.stale ? ' <b style="color:#f87171">(cached — FIRMS unreachable)</b>' : ''}<br>Source: NASA FIRMS`;
    return d;
  } catch (e) {
    state.all = [];
    state.meta = null;
    meta.innerHTML = `<span style="color:#f87171">Active fires unavailable: ${e.message}</span><br>Start the backend (see README) and set FIRMS_MAP_KEY.`;
    toast(`Active fires unavailable: ${e.message}`, true);
    return null;
  } finally {
    applyFilters(map);
  }
}

export function currentFilters() {
  const confs = [...document.querySelectorAll('#conf-filter input:checked')].map(i => i.value);
  return { confs: new Set([...confs, ...(confs.length === 3 ? ['unknown'] : [])]), frpMin: +document.getElementById('frp-min').value };
}

export function applyFilters(map) {
  const { confs, frpMin } = currentFilters();
  const T = state.tCur;
  const feats = [];
  for (const f of state.all) {
    const p = f.properties;
    const t = Date.parse(p.t);
    if (t > T || !confs.has(p.cc) || (p.frp ?? 0) < frpMin) continue;
    feats.push({ type: 'Feature', geometry: f.geometry, properties: { ...p, age_h: (T - t) / 3.6e6 } });
  }
  state.shown = { type: 'FeatureCollection', features: feats };
  map.getSource('fires')?.setData(state.shown);
  map.getSource('fires-c')?.setData(state.shown);
  document.dispatchEvent(new CustomEvent('fires:filtered', { detail: state }));
}

export function setStyle(map, style) {
  state.style = style;
  refreshVisibility(map);
}

export function refreshVisibility(map) {
  const on = state.on;
  setVis(map, POINT_LAYERS, on && state.style === 'points');
  setVis(map, HEAT_LAYERS, on && state.style === 'heat');
  setVis(map, CLUSTER_LAYERS, on && state.style === 'cluster');
}

export function exportFires(kind) {
  if (!state.shown.features.length) return toast('No detections to export', true);
  const src = state.meta?.source ?? 'firms';
  if (kind === 'geojson') return download(`kpsterra_${src}.geojson`, JSON.stringify(state.shown), 'application/geo+json');
  const cols = ['t', 'sat', 'inst', 'frp', 'conf', 'cc', 'bt', 'dn', 'scan', 'track', 'ver'];
  const rows = state.shown.features.map(f => [f.geometry.coordinates[1], f.geometry.coordinates[0], ...cols.map(c => f.properties[c] ?? '')].join(','));
  download(`kpsterra_${src}.csv`, ['latitude,longitude,acq_datetime_utc,satellite,instrument,frp_mw,confidence,conf_class,brightness_k,daynight,scan_km,track_km,version', ...rows].join('\n'));
}
