import { API, fmt, getJSON, toast } from './config.js';
import { addLabelLayers, createMap, setBasemap, setGibsBasemapTime, setLabels, setView, setVis } from './map.js';
import * as wind from './wind.js';
import * as overlays from './layers.js';
import * as measure from './measure.js';
import { renderLegend } from './legend.js';
import * as sim from './simui.js';
import { mountAll as mountLogos } from './logo.js';

mountLogos();
import * as fires from './fires.js';
import * as sats from './satellites.js';
import * as draw from './draw.js';
import { addHistoryLayers, bboxOf, gridGeoJSON, highlightState, hist, loadStatic, setChoropleth } from './history.js';
import { renderStats } from './stats.js';
import { renderAbout, renderAnalytics, renderCatalogue, renderIndia, renderPlanned } from './pages.js';
import { renderClimate, resizeClimate } from './climate.js';

const $ = id => document.getElementById(id);
const PRODUCT = 'MODIS C6.1 Terra+Aqua, type 0';
// Static data is loaded independently of the map, so other pages work even if the map is slow or fails.
const staticReady = loadStatic();
const map = createMap();
window.kpsterraMap = map;   // handy for debugging in the browser console
let infoMode = 'region';

// ---------- popovers & rail ----------
const POPS = ['layers', 'basemaps', 'legend', 'info', 'sim'];
function setPop(name, open) {
  const el = $(name);
  if (!el) return;
  // only one rail-side popover at a time; the layer list (left) can stay open alongside
  if (open && name !== 'layers') POPS.filter(p => p !== name && p !== 'layers').forEach(p => setPop(p, false));
  el.hidden = !open;
  document.querySelector(`.rail [data-pop="${name}"]`)?.classList.toggle('active', open);
  if (open && name === 'info') window.dispatchEvent(new Event('resize'));
}
const togglePop = name => setPop(name, $(name).hidden);
document.querySelectorAll('.rail [data-pop]').forEach(b => (b.onclick = () => togglePop(b.dataset.pop)));
document.querySelectorAll('[data-close]').forEach(b => (b.onclick = () => setPop(b.dataset.close, false)));

function syncRail() {
  document.querySelector('.rail [data-tog="sats"]').classList.toggle('on', $('lyr-sats').checked);
  document.querySelector('.rail [data-tog="wind"]').classList.toggle('on', $('lyr-wind').checked);
}

function tickClock() {
  const now = new Date();
  $('clock-utc').textContent = now.toISOString().slice(11, 16);
  $('clock-ist').textContent = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' });
}
tickClock();
setInterval(tickClock, 1000);

// ---------- right panel ----------
function liveSummary() {
  const s = fires.state;
  if (!s.meta) return '';
  const f = s.shown.features;
  const maxFrp = f.reduce((m, x) => Math.max(m, x.properties.frp ?? 0), 0);
  return `<h3 style="margin-top:10px">Live detections (filtered)</h3>
    <div class="cards"><div class="card"><div class="v">${fmt(f.length)}</div><div class="k">${s.meta.source_label}, last ${s.meta.days * 24} h</div></div>
    <div class="card"><div class="v">${fmt(maxFrp, 0)}</div><div class="k">max FRP (MW)</div></div></div>
    <div class="btns"><button class="btn" id="dl-csv">⤓ Live CSV</button><button class="btn" id="dl-gj">⤓ Live GeoJSON</button></div>
    <h3>History · ${PRODUCT}</h3>`;
}

function bindLiveButtons() {
  $('dl-csv') && ($('dl-csv').onclick = () => fires.exportFires('csv'));
  $('dl-gj') && ($('dl-gj').onclick = () => fires.exportFires('geojson'));
}

function showRegion(name, open = true) {
  infoMode = 'region';
  const s = name ? hist.stats.states[name] : hist.stats.india_in_boundary;
  if (name && !s) return toast(`No statistics for ${name}`, true);
  highlightState(map, name);
  $('info-title').textContent = `${name || 'India'} · fire history`;
  renderStats($('info-body'), s, { title: name || 'India', product: PRODUCT, params: { region: name || 'India (inside boundary)', source: 'data/state_stats.json' }, extraTop: liveSummary() });
  bindLiveButtons();
  if (open) setPop('info', true);
  showRegion.current = name;
}

async function showPolygon(geometry) {
  infoMode = 'polygon';
  highlightState(map, null);
  $('info-title').textContent = 'Custom area · computing…';
  $('info-body').innerHTML = '<p class="muted">Querying the MODIS archive…</p>';
  setPop('info', true);
  try {
    const s = await getJSON(`${API}/api/stats/polygon`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ geometry }) });
    $('info-title').textContent = `Custom area · ${fmt(s.area_km2)} km²`;
    renderStats($('info-body'), s, { title: 'custom_area', product: PRODUCT, params: { region: 'custom polygon', geometry, area_km2: s.area_km2 } });
  } catch (e) {
    $('info-title').textContent = 'Custom area';
    $('info-body').innerHTML = `<p style="color:#f87171">Statistics unavailable: ${e.message}</p><p class="muted">Custom-area statistics need the FastAPI backend (state statistics work without it).</p>`;
  }
}

function showSat(s, p, tickOnly = false) {
  if (tickOnly && infoMode !== 'sat') return;
  infoMode = 'sat';
  $('info-title').textContent = `${s.info.name} · orbit estimate`;
  $('info-body').innerHTML = sats.satInfoHTML(s, p);
  if (!tickOnly) setPop('info', true);
}

// ---------- fires ----------
const fireParams = () => ({ source: $('fire-source').value, days: $('fire-days').value, region: $('fire-region').value });

async function reloadFires() {
  await fires.loadFires(map, fireParams());
  setupTimeline();
  if (infoMode === 'region') showRegion(showRegion.current, false);
}

function setupTimeline() {
  const s = fires.state;
  const t = $('time');
  t.min = 0;
  t.max = Math.max(1, Math.round((s.tMax - s.tMin) / 600000));   // 10-min steps
  t.value = t.max;
  updateTimeLabel();
}

function updateTimeLabel() {
  const s = fires.state;
  if (!s.meta) return ($('time-label').textContent = 'No live detections loaded');
  $('time-label').textContent = `Detections up to ${new Date(s.tCur).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

$('time').oninput = () => {
  const s = fires.state;
  s.tCur = s.tMin + (+$('time').value) * 600000;
  if (+$('time').value >= +$('time').max) s.tCur = s.tMax;
  updateTimeLabel();
  fires.applyFilters(map);
};

let playTimer = null;
$('play').onclick = () => {
  if (playTimer) { clearInterval(playTimer); playTimer = null; $('play').textContent = '▶'; return; }
  const t = $('time');
  if (+t.value >= +t.max) t.value = 0;
  $('play').textContent = '❚❚';
  const step = Math.max(1, Math.round(t.max / 120));
  playTimer = setInterval(() => {
    t.value = Math.min(+t.max, +t.value + step);
    t.oninput();
    if (+t.value >= +t.max) $('play').onclick();
  }, 80);
};

// ---------- controls ----------
function wireControls() {
  ['fire-source', 'fire-days', 'fire-region'].forEach(id => ($(id).onchange = reloadFires));
  $('fire-style').onchange = () => fires.setStyle(map, $('fire-style').value);
  $('conf-filter').onchange = () => fires.applyFilters(map);
  $('frp-min').oninput = () => { $('frp-val').textContent = $('frp-min').value; fires.applyFilters(map); };
  $('lyr-fires').onchange = () => { fires.state.on = $('lyr-fires').checked; fires.refreshVisibility(map); };
  $('lyr-states').onchange = () => setVis(map, ['states-line', 'states-fill', 'states-sel'], $('lyr-states').checked);
  $('lyr-choro').onchange = () => setChoropleth(map, $('lyr-choro').checked);
  $('lyr-sats').onchange = () => { sats.setVisible(map, $('lyr-sats').checked); syncRail(); };
  $('basemap').onchange = () => setBasemap(map, $('basemap').value);
  $('lyr-labels').onchange = () => setLabels(map, $('lyr-labels').checked);
  $('lyr-wind').onchange = async () => {
    syncRail();
    if (!$('lyr-wind').checked) return wind.stopWind();
    $('meta-wind').textContent = 'Loading GFS wind…';
    try {
      const g = await wind.loadWind();
      $('meta-wind').textContent = `NOAA GFS 1° analysis, valid ${g.valid_time_utc.replace('T', ' ').replace('Z', ' UTC')}${g.stale ? ' (cached)' : ''}`;
      if ($('lyr-wind').checked) wind.startWind(map);
    } catch (e) {
      $('meta-wind').innerHTML = `<span style="color:#f87171">Wind unavailable: ${e.message}</span>`;
      $('lyr-wind').checked = false;
      syncRail();
    }
  };
  document.querySelectorAll('[data-gibs]').forEach(cb => (cb.onchange = () => overlays.toggleGibs(map, cb.dataset.gibs, cb.checked)));
  $('img-op').oninput = () => { $('img-op-v').textContent = `${$('img-op').value}%`; overlays.setImageryOpacity(map, $('img-op').value / 100); };
  $('lyr-gdacs').onchange = () => overlays.toggleHazard(map, 'gdacs', $('lyr-gdacs').checked);
  $('lyr-tc').onchange = () => overlays.toggleHazard(map, 'tc', $('lyr-tc').checked);
  $('lyr-inc-us').onchange = () => overlays.toggleIncidents(map, 'us', $('lyr-inc-us').checked);
  $('lyr-inc-ca').onchange = () => overlays.toggleIncidents(map, 'canada', $('lyr-inc-ca').checked);
  $('layer-q').oninput = () => {
    const q = $('layer-q').value.trim().toLowerCase();
    document.querySelectorAll('#layers .lyr').forEach(l => (l.hidden = q && !(l.dataset.k + ' ' + l.textContent).toLowerCase().includes(q)));
    document.querySelectorAll('#layers .grp').forEach(g => (g.open = true));
  };
  document.querySelectorAll('.rail [data-tog]').forEach(b => (b.onclick = () => {
    const cb = $(`lyr-${b.dataset.tog}`);
    cb.checked = !cb.checked;
    cb.onchange();
  }));

  const years = hist.grid.years;
  const gy = $('grid-year');
  gy.min = years[0] - 1;
  gy.max = years[years.length - 1];
  gy.value = gy.min;
  const updGrid = () => {
    const y = +gy.value < years[0] ? null : +gy.value;
    $('grid-year-val').textContent = y ?? 'all-year mean';
    map.getSource('grid').setData(gridGeoJSON(y));
  };
  gy.oninput = updGrid;
  $('lyr-grid').onchange = () => {
    setVis(map, ['grid'], $('lyr-grid').checked);
    if ($('lyr-grid').checked) updGrid();
  };

  document.querySelectorAll('#proj-seg button').forEach(b => (b.onclick = () => {
    document.querySelectorAll('#proj-seg button').forEach(x => x.classList.toggle('active', x === b));
    setView(map, b.dataset.proj);
  }));
  document.querySelectorAll('#sat-filter button').forEach(b => (b.onclick = () => {
    document.querySelectorAll('#sat-filter button').forEach(x => x.classList.toggle('active', x === b));
    sats.setFilter(map, b.dataset.f, showSat);
  }));
  document.querySelector('.rail [data-tool="sim"]').onclick = () => {
    if (draw.isDrawing()) draw.stop(map, true);
    if (measure.isMeasuring()) { measure.toggle(map, false); document.querySelector('.rail [data-tool="measure"]').classList.remove('active'); }
    sim.toggle();
  };
  $('sim-close').onclick = () => { sim.setPicking(false); sim.closePanel(); };
  const measureBtn = document.querySelector('.rail [data-tool="measure"]');
  measureBtn.onclick = () => {
    if (draw.isDrawing()) draw.stop(map, true);
    measure.toggle(map, !measure.isMeasuring());
    measureBtn.classList.toggle('active', measure.isMeasuring());
  };
  $('draw-btn').onclick = () => {
    if (measure.isMeasuring()) { measure.toggle(map, false); measureBtn.classList.remove('active'); }
    draw.isDrawing() ? draw.stop(map, true) : draw.start(map, showPolygon);
  };
  document.querySelector('.rail [data-tool="share"]').onclick = async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      toast('Link to this view copied');
    } catch {
      toast(`Copy this link: ${location.href}`, false, 9000);
    }
  };
  $('png-btn').onclick = () => {
    const a = document.createElement('a');
    a.href = map.getCanvas().toDataURL('image/png');
    a.download = `kpsterra_map_${new Date().toISOString().slice(0, 10)}.png`;
    a.click();
  };

  $('state-list').innerHTML = Object.keys(hist.stats.states).sort().map(n => `<option value="${n}">`).join('');
  $('search').onchange = () => {
    const q = $('search').value.trim();
    const m = q.match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
    if (m) {
      const [lat, lon] = [+m[1], +m[2]];
      if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return toast('Coordinates out of range', true);
      map.flyTo({ center: [lon, lat], zoom: 9 });
      new maplibregl.Popup().setLngLat([lon, lat]).setHTML(`${lat.toFixed(4)}, ${lon.toFixed(4)}`).addTo(map);
      return;
    }
    const name = Object.keys(hist.stats.states).find(n => n.toLowerCase() === q.toLowerCase())
      ?? Object.keys(hist.stats.states).find(n => n.toLowerCase().includes(q.toLowerCase()));
    if (!name) return toast('Type a state name or "lat, lon"', true);
    goToState(name);
  };
}

function goToState(name) {
  showPage('map');
  if (!name) { map.flyTo({ center: [80, 22], zoom: 3.6 }); return showRegion(null); }
  const f = hist.states.features.find(x => x.properties.state_name === name);
  if (f) map.fitBounds(bboxOf(f.geometry), { padding: 60, maxZoom: 8 });
  showRegion(name);
}

// map clicks: fire popup > state selection
function wireMapClicks() {
  map.on('click', e => {
    if (e.kpsterraHandled || draw.isDrawing() || measure.isMeasuring() || sim.isPicking()) return;
    const ctx = map.queryRenderedFeatures(e.point, { layers: ['gdacs', 'inc-us', 'inc-canada'].filter(l => map.getLayer(l) && map.getLayoutProperty(l, 'visibility') !== 'none') });
    if (ctx.length) return;   // these layers open their own popups
    const hit = map.queryRenderedFeatures(e.point, { layers: ['fires-pt', 'fires-cl', 'fires-cl-pt'].filter(l => map.getLayoutProperty(l, 'visibility') !== 'none') });
    if (hit.length) {
      if (hit[0].layer.id === 'fires-cl') return;
      const f = hit[0];
      new maplibregl.Popup({ maxWidth: '320px' }).setLngLat(f.geometry.coordinates).setHTML(fires.popupHTML(f.properties, f.geometry.coordinates)).addTo(map);
      return;
    }
    if ($('lyr-grid').checked) {
      const g = map.queryRenderedFeatures(e.point, { layers: ['grid'] })[0];
      if (g) {
        new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<b>0.25° cell</b><br>${fmt(g.properties.v, 1)} detections (${$('grid-year-val').textContent})<br>mean FRP ${fmt(g.properties.frp, 1)} MW`).addTo(map);
      }
    }
    const st = map.queryRenderedFeatures(e.point, { layers: ['states-fill'] })[0];
    if (st && $('lyr-states').checked) showRegion(st.properties.state_name);
  });
}

// ---------- pages ----------
const rendered = new Set();
function showPage(p) {
  document.querySelectorAll('.page').forEach(x => x.classList.toggle('active', x.id === `page-${p}`));
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === p));
  $('nav').classList.remove('open');
  if (!rendered.has(p)) {
    rendered.add(p);
    const render = ({ analytics: renderAnalytics, india: () => renderIndia(goToState), climate: renderClimate, catalogue: renderCatalogue, about: renderAbout })[p];
    if (render) {
      const el = $(`page-${p}`);
      if (!el.innerHTML.trim()) el.innerHTML = '<p class="muted">Loading…</p>';
      staticReady.then(render).then(() => mountLogos(el)).catch(e => {
        rendered.delete(p);
        el.innerHTML = `<p style="color:#f87171">Could not load data for this page: ${e.message}</p>`;
      });
    }
  }
  if (p === 'map') map.resize();
  if (p === 'climate') resizeClimate();
  window.dispatchEvent(new Event('resize'));
}
document.querySelectorAll('#nav button').forEach(b => (b.onclick = () => showPage(b.dataset.page)));
$('menu-btn').onclick = () => $('nav').classList.toggle('open');

// ---------- boot ----------
renderPlanned();   // static text pages need nothing from the map

map.once('style.load', async () => {
  try {
    await staticReady;
  } catch (e) {
    toast(`Could not load historical data: ${e.message}`, true);
    return;
  }
  addHistoryLayers(map);
  overlays.addHazardLayers(map);
  overlays.addIncidentLayers(map);
  fires.addFireLayers(map);
  addLabelLayers(map);
  sats.addSatLayers(map);
  draw.addDrawLayers(map);
  measure.addMeasureLayers(map);
  sim.addSimLayers(map);
  renderLegend();
  wireControls();
  wireMapClicks();
  showRegion(null, false);
  sats.loadSatellites(map, showSat);
  reloadFires();
  overlays.loadGibsTimes().then(() => {
    const t = overlays.gibsTime('VIIRS_SNPP_CorrectedReflectance_TrueColor');
    if (t) setGibsBasemapTime(map, t);
  });
  $('lyr-wind').checked = true;   // wind on by default, like the reference design
  $('lyr-wind').onchange();
});
