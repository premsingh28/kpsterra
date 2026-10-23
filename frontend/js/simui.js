// Rothermel fire-spread simulation: pick an ignition point, set inputs, run, and draw perimeters.
import { API, download, fmt, getJSON, toast } from './config.js';
import { windAt } from './wind.js';
import { chart } from './stats.js';

const $ = id => document.getElementById(id);
const EMPTY = { type: 'FeatureCollection', features: [] };
let picking = false, map = null, point = null, marker = null, last = null, fuels = null;
const COMPASS = d => ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][Math.round(d / 22.5) % 16];

export function addSimLayers(m) {
  map = m;
  map.addSource('sim-perim', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'sim-perim', type: 'line', source: 'sim-perim', paint: {
    'line-color': ['interpolate', ['linear'], ['get', 'hours'], 0, '#fff3b0', 3, '#ff8c42', 6, '#e8233a', 12, '#7a1b6e', 24, '#3b0a45'],
    'line-width': ['case', ['==', ['get', 'last'], true], 3, 1.6] } });
  map.on('click', e => {
    if (!picking) return;
    e.kpsterraHandled = true;     // stop the general map click (state selection) from also firing
    setPicking(false);
    place(e.lngLat.lat, e.lngLat.lng);
  });
}

export const isPicking = () => picking;

export function setPicking(on) {
  picking = on;
  map.getCanvas().style.cursor = on ? 'crosshair' : '';
  const hint = $('draw-hint');
  hint.classList.toggle('hidden', !on);
  if (on) hint.textContent = 'Click the map to place the ignition point · Esc to cancel';
  document.querySelector('.rail [data-tool="sim"]').classList.toggle('active', on || !$('sim').hidden);
}
window.addEventListener('keydown', e => e.key === 'Escape' && picking && setPicking(false));

async function loadFuels() {
  fuels ??= await getJSON(`${API}/api/sim/fuel-models`);
  return fuels;
}

async function place(lat, lon) {
  point = { lat, lon };
  marker?.remove();
  const el = document.createElement('div');
  el.innerHTML = '🔥';
  el.style.cssText = 'font-size:22px;filter:drop-shadow(0 0 6px #ff6b35)';
  marker = new maplibregl.Marker({ element: el, anchor: 'bottom' }).setLngLat([lon, lat]).addTo(map);
  openPanel();
  let fl;
  try { fl = await loadFuels(); } catch (e) { $('sim-body').innerHTML = `<p style="color:#f87171">Simulation needs the backend: ${e.message}</p>`; return; }
  const w = windAt(lon, lat);
  // GFS gives 10 m wind; Rothermel uses 20-ft (6.1 m) wind: 10 m speed / 1.15 (BehavePlus convention)
  const w20 = w ? (w.speed_ms * 3.6 / 1.15) : 10;
  $('sim-body').innerHTML = `
    <p class="meta">Ignition ${lat.toFixed(4)}°, ${lon.toFixed(4)}° · <a href="#" id="sim-move">move</a></p>
    <label>Fuels</label>
    <div class="seg small" id="sim-mode"><button data-m="landcover" class="active">Land-cover map</button><button data-m="uniform">Single fuel model</button></div>
    <div id="sim-lc-opts"><label>Land-cover source<select id="sim-src">
        <option value="recent" selected>Recent: ESA WorldCover 2021 (10 m) + MODIS 2025 forest types</option>
        <option value="ornl2005">ORNL India LULC 2005 (100 m)</option><option value="ornl1995">ORNL India LULC 1995</option>
        <option value="ornl1985">ORNL India LULC 1985</option></select></label>
      <p class="meta">Each land-cover class maps to a fuel model; water, built-up, bare, wetlands and snow are non-burnable. <a href="#" id="sim-xwalk">Show crosswalk</a></p>
      <div id="sim-xwalk-tbl" hidden></div></div>
    <label><span id="sim-fuel-lbl">Fallback fuel (outside India)</span><select id="sim-fuel">${fl.map(f => `<option value="${f.id}" ${f.id === 9 ? 'selected' : ''}>${f.code}: ${f.name}</option>`).join('')}</select></label>
    <p class="meta" id="sim-fuel-hint"></p>
    <div class="row">
      <label>Wind 20-ft (km/h)<input id="sim-ws" type="number" min="0" max="120" step="0.5" value="${w20.toFixed(1)}"></label>
      <label>Wind from (°)<input id="sim-wd" type="number" min="0" max="360" step="5" value="${w ? Math.round(w.from_deg) : 270}"></label>
    </div>
    <p class="meta">${w ? `Auto-filled from ${w.source}, valid ${w.valid_time.replace('T', ' ').replace('Z', ' UTC')} (10 m: ${(w.speed_ms * 3.6).toFixed(1)} km/h from ${COMPASS(w.from_deg)})` : 'Wind layer not loaded: default values'}</p>
    <fieldset class="sim-moist"><legend>Fuel moisture (%)</legend>
      <label>1-h<input id="sim-m1" type="number" min="1" max="60" value="6"></label>
      <label>10-h<input id="sim-m10" type="number" min="1" max="60" value="8"></label>
      <label>100-h<input id="sim-m100" type="number" min="1" max="60" value="10"></label>
      <label>Live herb<input id="sim-mh" type="number" min="30" max="300" value="60"></label>
      <label>Live woody<input id="sim-mw" type="number" min="30" max="300" value="90"></label>
    </fieldset>
    <p class="meta">Defaults: dry pre-monsoon conditions in Indian forests (Mar–May).</p>
    <div class="row">
      <label>Canopy cover (%)<input id="sim-cc" type="number" min="0" max="100" value="0"></label>
      <label>Canopy height (m)<input id="sim-ch" type="number" min="0" max="80" value="0"></label>
    </div>
    <div class="row">
      <label>Duration<select id="sim-h"><option>1</option><option>2</option><option>3</option><option selected>6</option><option>12</option><option>24</option></select></label>
      <label>WAF override<input id="sim-waf" type="number" min="0.05" max="1" step="0.01" placeholder="auto"></label>
    </div>
    <div class="btns"><button class="btn primary" id="sim-run">▶ Run simulation</button><button class="btn" id="sim-clear">Clear</button></div>
    <div id="sim-out"></div>`;
  const hint = () => { const f = fl.find(x => x.id === +$('sim-fuel').value); $('sim-fuel-hint').textContent = `India: ${f.india_hint} · bed depth ${f.depth_m} m · dead Mx ${f.mx_dead_pct} %${f.dynamic ? ' · dynamic (herb curing)' : ''}`; };
  $('sim-fuel').onchange = hint;
  hint();
  document.querySelectorAll('#sim-mode button').forEach(b => (b.onclick = () => {
    document.querySelectorAll('#sim-mode button').forEach(x => x.classList.toggle('active', x === b));
    const lc = b.dataset.m === 'landcover';
    $('sim-lc-opts').hidden = !lc;
    $('sim-fuel-lbl').textContent = lc ? 'Fallback fuel (outside India)' : 'Fuel model';
  }));
  const loadXwalk = async () => {
    const box = $('sim-xwalk-tbl');
    try {
      const x = await getJSON(`${API}/api/sim/fuel-crosswalk?source=${$('sim-src').value}`);
      box.innerHTML = `<p class="meta"><b>${x.label}</b>${x.available ? '' : ' (data not found on the server)'}</p>
        <table class="xw">${x.classes.map(c => `<tr><td><i class="sw" style="background:${c.color}"></i>${c.name}</td><td>${c.fuel}</td></tr>`).join('')}</table>
        <p class="meta">The crosswalk is an assumption for pre-monsoon conditions, not a field-calibrated fuel map. Edit it in backend/app/services/fuelmap.py.</p>`;
    } catch (err) { box.textContent = `Unavailable: ${err.message}`; }
  };
  $('sim-xwalk').onclick = e => {
    e.preventDefault();
    $('sim-xwalk-tbl').hidden = !$('sim-xwalk-tbl').hidden;
    if (!$('sim-xwalk-tbl').hidden) loadXwalk();
  };
  $('sim-src').onchange = () => { if (!$('sim-xwalk-tbl').hidden) loadXwalk(); };
  $('sim-move').onclick = e => { e.preventDefault(); setPicking(true); };
  $('sim-run').onclick = run;
  $('sim-clear').onclick = clear;
}

function openPanel() {
  document.querySelectorAll('.pop').forEach(p => { if (p.id !== 'layers' && p.id !== 'sim') p.hidden = true; });
  document.querySelectorAll('.rail [data-pop]').forEach(b => b.dataset.pop !== 'layers' && b.classList.remove('active'));
  $('sim').hidden = false;
  document.querySelector('.rail [data-tool="sim"]').classList.add('active');
}

export function closePanel() {
  $('sim').hidden = true;
  document.querySelector('.rail [data-tool="sim"]').classList.remove('active');
}

export function toggle() {
  if (!$('sim').hidden || picking) { setPicking(false); closePanel(); return; }
  if (point) { openPanel(); return; }
  setPicking(true);
}

async function run() {
  const num = id => +$(id).value;
  const body = { lat: point.lat, lon: point.lon, fuel: num('sim-fuel'), wind_20ft_kmh: num('sim-ws'), wind_from_deg: num('sim-wd') % 360,
    hours: num('sim-h'), canopy_cover_pct: num('sim-cc'), canopy_height_m: num('sim-ch'),
    fuel_mode: document.querySelector('#sim-mode .active').dataset.m, lc_source: $('sim-src').value,
    moisture: { '1h': num('sim-m1'), '10h': num('sim-m10'), '100h': num('sim-m100'), herb: num('sim-mh'), woody: num('sim-mw') } };
  if ($('sim-waf').value) body.waf = num('sim-waf');
  $('sim-out').innerHTML = '<p class="muted">Fetching terrain and simulating…</p>';
  $('sim-run').disabled = true;
  try {
    const r = await getJSON(`${API}/api/sim/rothermel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), timeout: 120000 });
    last = { request: body, result: r };
    draw(r);
  } catch (e) {
    $('sim-out').innerHTML = `<p style="color:#f87171">Simulation failed: ${e.message}</p>`;
  } finally {
    $('sim-run').disabled = false;
  }
}

function draw(r) {
  if (!r.burnable) {
    clearLayers();
    $('sim-out').innerHTML = `<p style="color:#fbbf24"><b>No spread.</b> ${r.reason}</p>`;
    return;
  }
  clearLayers();
  if (r.fuel_png) {
    map.addSource('sim-fuel', { type: 'image', url: r.fuel_png, coordinates: r.bounds });
    map.addLayer({ id: 'sim-fuel', type: 'raster', source: 'sim-fuel', layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0.7, 'raster-resampling': 'nearest' } }, 'sim-perim');
  }
  map.addSource('sim-arrival', { type: 'image', url: r.arrival_png, coordinates: r.bounds });
  map.addLayer({ id: 'sim-arrival', type: 'raster', source: 'sim-arrival', paint: { 'raster-opacity': 0.75, 'raster-resampling': 'nearest' } }, 'sim-perim');
  const feats = r.perimeters.features.map((f, i, a) => ({ ...f, properties: { ...f.properties, last: i === a.length - 1 } }));
  map.getSource('sim-perim').setData({ type: 'FeatureCollection', features: feats });
  const [[x0, y0], , [x1, y1]] = r.bounds;
  map.fitBounds([[Math.min(x0, x1), Math.min(y0, y1)], [Math.max(x0, x1), Math.max(y0, y1)]], { padding: 40, maxZoom: 15, duration: 900 });

  const p = r.point, ig = r.ignition, inp = r.inputs;
  const fl = p.flame_length_m;
  const severity = fl < 1.2 ? ['Low', '#22c55e', 'hand crews can attack the head'] : fl < 2.4 ? ['Moderate', '#facc15', 'too intense for direct hand-crew attack at the head'] :
    fl < 3.4 ? ['High', '#f97316', 'equipment needed; control at the head unlikely'] : ['Very high', '#ef4444', 'major runs; direct control not possible'];
  $('sim-out').innerHTML = `
    <div class="cards">
      <div class="card"><div class="v">${fmt(r.final_area_ha, 1)} ha</div><div class="k">area after ${inp.hours} h</div></div>
      <div class="card"><div class="v">${fmt(p.ros_head_m_min, 2)}</div><div class="k">head spread (m/min) at ignition</div></div>
      <div class="card"><div class="v">${fmt(fl, 2)} m</div><div class="k">flame length</div></div>
      <div class="card"><div class="v">${fmt(p.fireline_intensity_kw_m, 0)}</div><div class="k">fireline intensity (kW/m)</div></div>
    </div>
    <p class="note" style="border-color:${severity[1]}"><b style="color:${severity[1]}">${severity[0]} intensity</b>: ${severity[2]} (Andrews & Rothermel 1982 hauling chart).</p>
    <dl class="kv">
      <dt>Max spread toward</dt><dd>${Math.round(p.dir_max_spread_deg)}° (${COMPASS(p.dir_max_spread_deg)})</dd>
      <dt>Backing / flanking</dt><dd>${fmt(p.ros_back_m_min, 2)} / ${fmt(p.ros_flank_m_min, 2)} m/min</dd>
      <dt>Length : width</dt><dd>${fmt(p.length_to_width, 2)}</dd>
      <dt>Midflame wind</dt><dd>${fmt(p.midflame_wind_kmh, 1)} km/h (WAF ${fmt(inp.waf, 2)}, ${p.waf_source})</dd>
      <dt>Effective wind</dt><dd>${fmt(p.effective_wind_kmh, 1)} km/h${p.wind_limited ? ' (wind limit applied)' : ''}</dd>
      <dt>Reaction intensity</dt><dd>${fmt(p.reaction_intensity_kw_m2, 0)} kW/m²</dd>
      <dt>Heat per unit area</dt><dd>${fmt(p.heat_per_area_kj_m2, 0)} kJ/m²</dd>
      <dt>Ignition terrain</dt><dd>${fmt(ig.elevation_m, 0)} m, slope ${ig.slope_pct} %, aspect ${ig.aspect_deg}° (${COMPASS(ig.aspect_deg)})</dd>
      <dt>Ignition fuel</dt><dd>${ig.fuel}${ig.landcover ? ` (${ig.landcover})` : ''}</dd>
      <dt>Domain</dt><dd>${r.grid.n}×${r.grid.n} cells of ${inp.cell_m} m · elevation ${r.grid.elev_min}–${r.grid.elev_max} m${r.nonburnable_pct ? ` · ${r.nonburnable_pct} % non-burnable` : ''}</dd>
    </dl>
    ${r.landcover_summary ? `<h3 style="margin:10px 0 4px">Burned area by land cover</h3><p class="meta">${inp.lc_source_label}</p>
      <label class="chk" style="margin:4px 0"><input type="checkbox" id="sim-fuel-show"> Show fuel / land-cover map</label>
      <table class="xw"><tr><th>Class</th><th>Fuel</th><th>Domain</th><th>Burned</th></tr>
      ${r.landcover_summary.map(s => `<tr><td><i class="sw" style="background:${s.color}"></i>${s.name}</td><td>${s.fuel}</td><td>${s.domain_pct}%</td><td>${fmt(s.burned_ha, 0)} ha</td></tr>`).join('')}</table>
      ${inp.cell_m > 30 ? `<p class="meta">Grid cells are ${inp.cell_m} m; each takes the majority land-cover class inside it${inp.lc_source === 'recent' ? '' : ' (ORNL: nearest 100 m pixel)'}, so features much narrower than a cell can be lost.</p>` : ''}
      ${inp.lc_source !== 'recent' ? `<p class="meta">Historical land cover: check the area hasn't changed since.</p>` : ''}` : ''}
    ${r.unburnable_fuel_models?.length ? `<p class="note">Too wet to burn at these moistures: ${r.unburnable_fuel_models.join(', ')}</p>` : ''}
    ${r.reached_domain_edge ? '<p class="note" style="border-color:#f59e0b">The fire reached the edge of the simulation domain; the final area is underestimated.</p>' : ''}
    <div class="chart" id="sim-chart" style="height:170px"></div>
    <div class="btns"><button class="btn" id="sim-dl-gj">⤓ Perimeters (GeoJSON)</button><button class="btn" id="sim-dl-js">⤓ Inputs + results (JSON)</button></div>
    <p class="note">Rothermel (1972) surface spread with Albini (1976) weighting, checked against the USFS Fire Lab <i>behave</i> library. Terrain: AWS Open Data elevation (~30 m). ${inp.fuel_mode === 'landcover' ? 'Fuels: land-cover crosswalk (an assumption, not field-measured fuels). Assumes uniform moisture and weather,' : 'Assumes uniform fuel and weather,'} surface fire only (no crowning or spotting), and no roads, rivers or suppression. For research and teaching, not operational forecasting.</p>`;
  const f = r.perimeters.features;
  chart($('sim-chart'), { title: { text: 'Burned area over time (ha)', textStyle: { fontSize: 12, color: '#cbd5e1' } }, grid: { left: 46, right: 12, top: 30, bottom: 26 },
    xAxis: { type: 'category', data: f.map(x => `${x.properties.hours} h`), axisLabel: { color: '#94a3b8' } },
    yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.12)' } } },
    series: [{ type: 'line', data: f.map(x => x.properties.area_ha), areaStyle: { color: 'rgba(255,107,53,.2)' }, lineStyle: { color: '#ff6b35' }, itemStyle: { color: '#ff6b35' } }] });
  if ($('sim-fuel-show')) $('sim-fuel-show').onchange = e => map.setLayoutProperty('sim-fuel', 'visibility', e.target.checked ? 'visible' : 'none');
  $('sim-dl-gj').onclick = () => download('kpsterra_rothermel_perimeters.geojson', JSON.stringify(r.perimeters), 'application/geo+json');
  $('sim-dl-js').onclick = () => download('kpsterra_rothermel_run.json', JSON.stringify({ request: last.request, ...r, arrival_png: undefined, fuel_png: undefined,
    generated_utc: new Date().toISOString() }, null, 2), 'application/json');
}

function clearLayers() {
  for (const id of ['sim-arrival', 'sim-fuel']) {
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }
  map.getSource('sim-perim').setData(EMPTY);
}

function clear() {
  clearLayers();
  marker?.remove();
  marker = null;
  point = null;
  closePanel();
  toast('Simulation cleared');
}
