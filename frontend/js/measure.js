// Great-circle distance measuring tool.
const EMPTY = { type: 'FeatureCollection', features: [] };
let pts = [];
let active = false;

export const haversineKm = (a, b) => {
  const R = 6371.0088, rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
};

export function addMeasureLayers(map) {
  map.addSource('measure', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'measure-line', type: 'line', source: 'measure', paint: { 'line-color': '#fde047', 'line-width': 2, 'line-dasharray': [2, 1] } });
  map.addLayer({ id: 'measure-pt', type: 'circle', source: 'measure', filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#fde047' } });
  map.on('click', e => {
    if (!active) return;
    pts.push([e.lngLat.lng, e.lngLat.lat]);
    render(map);
  });
}

export const isMeasuring = () => active;

export function toggle(map, on) {
  active = on;
  pts = [];
  map.getCanvas().style.cursor = on ? 'crosshair' : '';
  const hint = document.getElementById('draw-hint');
  hint.classList.toggle('hidden', !on);
  hint.textContent = 'Click points to measure · click the ruler again to stop';
  render(map);
}

function render(map) {
  let total = 0;
  for (let i = 1; i < pts.length; i++) total += haversineKm(pts[i - 1], pts[i]);
  const feats = pts.map(p => ({ type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: {} }));
  if (pts.length > 1) feats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: pts }, properties: {} });
  map.getSource('measure').setData({ type: 'FeatureCollection', features: feats });
  if (active && pts.length > 1) {
    document.getElementById('draw-hint').textContent = `Distance: ${total.toLocaleString('en-IN', { maximumFractionDigits: total < 10 ? 2 : 0 })} km (great circle) · click the ruler to stop`;
  }
}
