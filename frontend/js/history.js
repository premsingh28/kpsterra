// Static historical layers: Survey-of-India state boundaries and the 0.25° MODIS density grid.
import { ACTIVITY } from './config.js';

export const hist = { states: null, stats: null, grid: null };

export async function loadStatic() {
  const [states, stats, grid] = await Promise.all(
    ['data/states.geojson', 'data/state_stats.json', 'data/grid_yearly.json'].map(u => fetch(u).then(r => r.json())));
  Object.assign(hist, { states, stats, grid });
  return hist;
}

export function addHistoryLayers(map) {
  const maxTotal = Math.max(...hist.states.features.map(f => f.properties.total));
  map.addSource('states', { type: 'geojson', data: hist.states, promoteId: 'state_name' });
  map.addLayer({ id: 'states-fill', type: 'fill', source: 'states', paint: {
    'fill-color': ['interpolate', ['linear'], ['sqrt', ['get', 'total']], 0, '#1e1b2e', Math.sqrt(maxTotal) * 0.5, '#9a3412', Math.sqrt(maxTotal), '#fb923c'],
    'fill-opacity': ['case', ['boolean', ['feature-state', 'choro'], false], 0.55, 0] } });
  map.addLayer({ id: 'states-line', type: 'line', source: 'states', paint: { 'line-color': '#94a3b8', 'line-width': 0.7, 'line-opacity': 0.6 } });
  map.addLayer({ id: 'states-sel', type: 'line', source: 'states', filter: ['==', ['get', 'state_name'], ''],
    paint: { 'line-color': '#38bdf8', 'line-width': 2.5 } });

  map.addSource('grid', { type: 'geojson', data: gridGeoJSON(null) });
  map.addLayer({ id: 'grid', type: 'fill-extrusion', source: 'grid', layout: { visibility: 'none' }, paint: {
    'fill-extrusion-color': ['step', ['get', 'v'], '#ffd166', ACTIVITY.medium, '#ff7b00', ACTIVITY.high, '#d00000'],
    'fill-extrusion-height': ['*', ['sqrt', ['get', 'v']], 9000],
    'fill-extrusion-opacity': 0.85 } }, 'states-line');
}

export function setChoropleth(map, on) {
  for (const f of hist.states.features) map.setFeatureState({ source: 'states', id: f.properties.state_name }, { choro: on });
}

export function highlightState(map, name) {
  map.setFilter('states-sel', ['==', ['get', 'state_name'], name ?? '']);
}

// year = null -> mean per year over all complete years
export function gridGeoJSON(year) {
  const g = hist.grid;
  if (!g) return { type: 'FeatureCollection', features: [] };
  const d = g.cell_deg;
  const yi = year == null ? -1 : g.years.indexOf(year);
  const nYears = g.years.length;
  const features = [];
  for (const c of g.cells) {
    const counts = c.slice(3);
    const v = yi < 0 ? counts.reduce((a, b) => a + b, 0) / nYears : counts[yi];
    if (v <= 0) continue;
    const [x, y] = c;
    features.push({ type: 'Feature', properties: { v: Math.round(v * 10) / 10, frp: c[2] },
      geometry: { type: 'Polygon', coordinates: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]] } });
  }
  return { type: 'FeatureCollection', features };
}

export function bboxOf(geom) {
  let [x0, y0, x1, y1] = [180, 90, -180, -90];
  const walk = c => (typeof c[0] === 'number' ? ([x0, y0, x1, y1] = [Math.min(x0, c[0]), Math.min(y0, c[1]), Math.max(x1, c[0]), Math.max(y1, c[1])]) : c.forEach(walk));
  walk(geom.coordinates);
  return [[x0, y0], [x1, y1]];
}
