const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
const TERRAIN = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
const ESRI = p => `https://server.arcgisonline.com/ArcGIS/rest/services/${p}/MapServer/tile/{z}/{y}/{x}`;
export const gibsURL = (layer, time, matrix, ext = 'png') =>
  `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${layer}/default/${time}/${matrix}/{z}/{y}/{x}.${ext}`;

// labels: which reference overlay sits on top (null = basemap already has labels)
const BASEMAPS = {
  sat: { tiles: [ESRI('World_Imagery')], attribution: 'Imagery © Esri, Maxar, Earthstar Geographics', maxzoom: 18, labels: 'Reference/World_Boundaries_and_Places' },
  dark: { tiles: [ESRI('Canvas/World_Dark_Gray_Base')], attribution: '© Esri, HERE, Garmin, © OpenStreetMap contributors', maxzoom: 16, labels: 'Canvas/World_Dark_Gray_Reference' },
  light: { tiles: [ESRI('Canvas/World_Light_Gray_Base')], attribution: '© Esri, HERE, Garmin, © OpenStreetMap contributors', maxzoom: 16, labels: 'Canvas/World_Light_Gray_Reference' },
  streets: { tiles: [ESRI('World_Street_Map')], attribution: '© Esri, HERE, Garmin, © OpenStreetMap contributors', maxzoom: 18, labels: null },
  topo: { tiles: [ESRI('World_Topo_Map')], attribution: '© Esri, HERE, Garmin, USGS, © OpenStreetMap contributors', maxzoom: 18, labels: null },
  gibs: { tiles: [gibsURL('VIIRS_SNPP_CorrectedReflectance_TrueColor', yesterday, 'GoogleMapsCompatible_Level9', 'jpg')],
    attribution: 'VIIRS Suomi-NPP true colour, NASA GIBS', maxzoom: 9, labels: 'Reference/World_Boundaries_and_Places' },
  night: { tiles: [gibsURL('VIIRS_Black_Marble', '2016-01-01', 'GoogleMapsCompatible_Level8')],
    attribution: 'VIIRS Black Marble 2016, NASA GIBS', maxzoom: 8, labels: 'Reference/World_Boundaries_and_Places' },
};
const LABEL_SETS = [...new Set(Object.values(BASEMAPS).map(b => b.labels).filter(Boolean))];
const labelId = p => 'labels-' + p.replace(/\W/g, '');
let current = 'sat';
let labelsOn = true;

export function createMap() {
  const sources = {};
  const layers = [];
  for (const [k, b] of Object.entries(BASEMAPS)) {
    sources[`base-${k}`] = { type: 'raster', tiles: b.tiles, tileSize: 256, attribution: b.attribution, maxzoom: b.maxzoom };
    layers.push({ id: `base-${k}`, type: 'raster', source: `base-${k}`, layout: { visibility: k === current ? 'visible' : 'none' } });
  }
  for (const p of LABEL_SETS) {
    sources[labelId(p)] = { type: 'raster', tiles: [ESRI(p)], tileSize: 256, maxzoom: 16 };
  }
  // Elevation for the 3D view (AWS Open Data terrain tiles, Terrarium encoding). Separate sources for
  // terrain and hillshade, as MapLibre recommends.
  const dem = { type: 'raster-dem', tiles: [TERRAIN], encoding: 'terrarium', tileSize: 256, maxzoom: 15,
    attribution: 'Terrain: Mapzen / AWS Open Data (SRTM, GMTED, ETOPO1)' };
  sources.dem = dem;
  sources['dem-hs'] = { ...dem };
  layers.push({ id: 'hillshade', type: 'hillshade', source: 'dem-hs', layout: { visibility: 'none' },
    paint: { 'hillshade-exaggeration': 0.45, 'hillshade-shadow-color': '#0b0b14', 'hillshade-highlight-color': '#ffffff' } });
  const map = new maplibregl.Map({
    container: 'map',
    style: { version: 8, sources, layers,
      sky: { 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0] } },
    center: [78, 21], zoom: 2.4, hash: true, maxPitch: 75,
    canvasContextAttributes: { preserveDrawingBuffer: true },
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
  map.on('style.load', () => map.setProjection({ type: 'globe' }));
  return map;
}

// Label overlays are added after the data layers so names stay on top of fire points.
export function addLabelLayers(map) {
  for (const p of LABEL_SETS) map.addLayer({ id: labelId(p), type: 'raster', source: labelId(p), layout: { visibility: 'none' } });
  refreshLabels(map);
}

function refreshLabels(map) {
  const want = labelsOn ? BASEMAPS[current].labels : null;
  for (const p of LABEL_SETS) map.getLayer(labelId(p)) && map.setLayoutProperty(labelId(p), 'visibility', p === want ? 'visible' : 'none');
}

export function setLabels(map, on) { labelsOn = on; refreshLabels(map); }

export function setBasemap(map, key) {
  current = key;
  for (const k of Object.keys(BASEMAPS)) map.setLayoutProperty(`base-${k}`, 'visibility', k === key ? 'visible' : 'none');
  refreshLabels(map);
}

// Point the "latest true colour" basemap at the newest GIBS date once the backend reports it.
export function setGibsBasemapTime(map, time) {
  const src = map.getSource('base-gibs');
  src?.setTiles?.([gibsURL('VIIRS_SNPP_CorrectedReflectance_TrueColor', time, 'GoogleMapsCompatible_Level9', 'jpg')]);
}

// globe | mercator (flat 2D) | 3d (terrain relief, exaggerated 1.6×, with hillshading)
export function setView(map, mode) {
  const is3d = mode === '3d';
  map.setTerrain(is3d ? { source: 'dem', exaggeration: 1.6 } : null);
  map.setLayoutProperty('hillshade', 'visibility', is3d ? 'visible' : 'none');
  if (mode === 'globe') {
    map.setProjection({ type: 'globe' });
    map.easeTo({ pitch: 0, bearing: 0 });
  } else if (mode === 'mercator') {
    map.setProjection({ type: 'mercator' });
    map.easeTo({ pitch: 0, bearing: 0 });
  } else {
    map.setProjection({ type: 'mercator' });
    map.easeTo({ pitch: 65, bearing: -20, zoom: Math.max(map.getZoom(), 5.5), duration: 1500 });
  }
}

export const setVis = (map, ids, on) => ids.forEach(id => map.getLayer(id) && map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'));
