// Minimal polygon drawing tool for custom-area statistics.
const EMPTY = { type: 'FeatureCollection', features: [] };
let pts = [];
let active = false;
let onDone = null;

export function addDrawLayers(map) {
  map.addSource('draw', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'draw-fill', type: 'fill', source: 'draw', paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.12 } });
  map.addLayer({ id: 'draw-line', type: 'line', source: 'draw', paint: { 'line-color': '#38bdf8', 'line-width': 2 } });
  map.addLayer({ id: 'draw-pt', type: 'circle', source: 'draw', filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#fff' } });

  map.on('click', e => {
    if (!active) return;
    pts.push([e.lngLat.lng, e.lngLat.lat]);
    render(map);
  });
  map.on('dblclick', e => {
    if (!active) return;
    e.preventDefault();
    finish(map);
  });
  window.addEventListener('keydown', e => e.key === 'Escape' && active && stop(map, true));
}

export const isDrawing = () => active;

export function start(map, cb) {
  active = true;
  pts = [];
  onDone = cb;
  map.doubleClickZoom.disable();
  map.getCanvas().style.cursor = 'crosshair';
  document.getElementById('draw-hint').classList.remove('hidden');
  document.getElementById('draw-btn').classList.add('on');
  render(map);
}

function finish(map) {
  // dblclick also fires two clicks; drop the duplicate vertex
  pts = pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]);
  if (pts.length < 3) return stop(map, true);
  const ring = [...pts, pts[0]];
  const geometry = { type: 'Polygon', coordinates: [ring] };
  stop(map, false);
  map.getSource('draw').setData({ type: 'Feature', geometry, properties: {} });
  onDone?.(geometry);
}

export function stop(map, clear) {
  active = false;
  map.doubleClickZoom.enable();
  map.getCanvas().style.cursor = '';
  document.getElementById('draw-hint').classList.add('hidden');
  document.getElementById('draw-btn').classList.remove('on');
  if (clear) map.getSource('draw').setData(EMPTY);
}

function render(map) {
  const feats = pts.map(p => ({ type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: {} }));
  if (pts.length > 1) feats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: pts.length > 2 ? [...pts, pts[0]] : pts }, properties: {} });
  map.getSource('draw').setData({ type: 'FeatureCollection', features: feats });
}
