// Non-map pages.
import { MONTHS, download, fmt } from './config.js';
import { hist } from './history.js';
import { chart, renderStats, trendText, peakMonth, yearlyOption } from './stats.js';

const $ = id => document.getElementById(id);
const PRODUCT = 'MODIS C6.1 Terra+Aqua, type 0';

export function renderAnalytics() {
  const el = $('page-analytics');
  const st = hist.stats.states;
  const rows = Object.entries(st).map(([name, s]) => ({ name, s, total: s.n })).sort((a, b) => b.total - a.total);
  el.innerHTML = `<h1>Fire Analytics</h1>
    <p class="lead">State rankings, trends and comparisons from the MODIS active-fire archive (${hist.stats.india.first_date} – ${hist.stats.india.last_date}). Values are satellite <b>detections</b> — not incidents and not burned area.</p>
    <div class="grid2">
      <div class="box"><div class="chart" id="an-rank" style="height:520px"></div></div>
      <div class="box">
        <label>Compare states (yearly detections)
          <select id="an-cmp" multiple size="6" style="width:100%">${rows.map((r, i) => `<option ${i < 4 ? 'selected' : ''}>${r.name}</option>`).join('')}</select></label>
        <div class="chart" id="an-cmp-chart" style="height:380px"></div>
      </div>
    </div>
    <div class="box" style="margin-top:16px;overflow-x:auto">
      <div class="btns"><button class="btn" id="an-dl">⤓ Download table (CSV)</button></div>
      <table><thead><tr><th>State</th><th>Detections</th><th>Mean / yr</th><th>Peak month</th><th>Median FRP (MW)</th><th>Trend (Mann–Kendall)</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td>${r.name}</td><td>${fmt(r.total)}</td><td>${fmt(r.total / r.s.years.length)}</td><td>${peakMonth(r.s)}</td><td>${fmt(r.s.frp.median, 1)}</td><td>${trendText(r.s.trend)}</td></tr>`).join('')}</tbody></table>
    </div>`;
  const top = rows.slice(0, 20).reverse();
  chart($('an-rank'), {
    title: { text: 'Top 20 states — total detections', textStyle: { fontSize: 13, color: '#cbd5e1' } },
    grid: { left: 150, right: 20, top: 34, bottom: 24 },
    xAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.12)' } } },
    yAxis: { type: 'category', data: top.map(r => r.name), axisLabel: { color: '#cbd5e1' } },
    series: [{ type: 'bar', data: top.map(r => r.total), itemStyle: { color: '#ff6b35' } }],
  });
  const drawCmp = () => {
    const names = [...$('an-cmp').selectedOptions].map(o => o.value).slice(0, 8);
    const years = hist.stats.india.years;
    chart($('an-cmp-chart'), {
      legend: { textStyle: { color: '#cbd5e1' }, top: 0 }, grid: { left: 54, right: 14, top: 50, bottom: 28 },
      xAxis: { type: 'category', data: years, axisLabel: { color: '#94a3b8' } },
      yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.12)' } } },
      series: names.map(n => ({ name: n, type: 'line', showSymbol: false, data: years.map(y => { const s = st[n]; const i = s.years.indexOf(y); return i < 0 ? 0 : s.yearly_count[i]; }) })),
    });
  };
  $('an-cmp').onchange = drawCmp;
  drawCmp();
  $('an-dl').onclick = () => download('kpsterra_state_summary.csv', ['state,detections,mean_per_year,peak_month,median_frp_mw,mk_trend,sen_slope_per_yr,mk_p',
    ...rows.map(r => [`"${r.name}"`, r.total, (r.total / r.s.years.length).toFixed(1), peakMonth(r.s), r.s.frp.median.toFixed(2), r.s.trend.trend, r.s.trend.sen_slope ?? '', r.s.trend.p ?? ''].join(','))].join('\n'));
}

export function renderIndia(goToMap) {
  const el = $('page-india');
  const names = Object.keys(hist.stats.states).sort();
  el.innerHTML = `<h1>India Fire Intelligence</h1>
    <p class="lead">Pick a state to see its fire history. District-level analysis needs district boundaries (planned). Official Forest Survey of India alerts are not connected: FSI does not offer a public API, and its alert definitions differ from raw satellite detections.</p>
    <div class="btns"><select id="in-state"><option value="">All India (inside boundary)</option>${names.map(n => `<option>${n}</option>`).join('')}</select>
      <button class="btn" id="in-map">Show on map</button></div>
    <div class="grid2"><div class="box" id="in-body"></div><div class="box"><div class="chart" id="in-yoy" style="height:360px"></div><p class="note">Year-on-year: each line is one year's monthly detections (last 6 years).</p></div></div>`;
  const draw = () => {
    const n = $('in-state').value;
    const s = n ? hist.stats.states[n] : hist.stats.india_in_boundary;
    renderStats($('in-body'), s, { title: n || 'India', product: PRODUCT, params: { region: n || 'India', source_file: 'data/state_stats.json' } });
    const byYear = {};
    s.monthly_index.forEach((m, i) => { const [y, mo] = m.split('-'); (byYear[y] ??= Array(12).fill(0))[+mo - 1] = s.monthly_count[i]; });
    const ys = Object.keys(byYear).slice(-6);
    chart($('in-yoy'), { legend: { textStyle: { color: '#cbd5e1' } }, grid: { left: 54, right: 14, top: 40, bottom: 28 },
      xAxis: { type: 'category', data: MONTHS, axisLabel: { color: '#94a3b8' } },
      yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.12)' } } },
      series: ys.map(y => ({ name: y, type: 'line', data: byYear[y], showSymbol: false })) });
  };
  $('in-state').onchange = draw;
  $('in-map').onclick = () => goToMap($('in-state').value);
  draw();
}

const planned = (title, lead, items, needs) => `<h1>${title} <span class="status planned">planned</span></h1>
  <p class="lead">${lead}</p>
  <div class="grid2"><div class="box"><h3>Planned features</h3><ul>${items.map(i => `<li>${i}</li>`).join('')}</ul></div>
  <div class="box"><h3>What it needs</h3><ul>${needs.map(i => `<li>${i}</li>`).join('')}</ul></div></div>`;

export function renderPlanned() {
  $('page-danger').innerHTML = planned('Fire Danger',
    'Show official fire-danger products only. Environmental danger, modelled occurrence probability and observed active fires are kept separate. No invented risk scores.',
    ['GEFF / GWIS Fire Weather Index maps and forecasts', 'Temperature, humidity, wind and recent rainfall for a selected place', 'Danger time series for a region', 'Any experimental model documented with training data and spatial/temporal validation'],
    ['CEMS / CDS access to GEFF FWI', 'Daily ingestion job']);
  $('page-research').innerHTML = planned('Research Workspace',
    'Project-based analysis: study area, period, datasets and methods saved together so results can be reproduced.',
    ['Create / save projects (study area upload, period, datasets)', 'Saved chart configurations', 'Export CSV, GeoJSON, PNG figures', 'Generated report: methods, sources, limitations, provenance'],
    ['Persistent storage (SQLite/PostGIS on the backend)', 'Safe GeoJSON / shapefile upload', 'Report template (HTML → PDF)']);
}

export async function renderCatalogue() {
  const el = $('page-catalogue');
  const cat = await fetch('data/catalogue.json').then(r => r.json());
  const cats = [...new Set(cat.map(c => c.category))];
  el.innerHTML = `<h1>Data Catalogue</h1>
    <p class="lead">Every dataset KPSTerra uses or plans to use. <span class="status connected">connected</span> = live in the app ·
    <span class="status static">static</span> = precomputed from a local archive · <span class="status credentials">needs credentials</span> ·
    <span class="status planned">planned</span> = not implemented yet.</p>
    <div class="catfilter"><input id="cat-q" type="search" placeholder="Search datasets…"><select id="cat-c"><option value="">All categories</option>${cats.map(c => `<option>${c}</option>`).join('')}</select></div>
    <div class="box" style="overflow-x:auto"><table><thead><tr><th>Dataset</th><th>Status</th><th>Category</th><th>Provider</th><th>Purpose</th><th>Coverage</th><th>Resolution</th><th>Period</th><th>Update</th><th>Access</th><th>Licence</th><th>Notes</th></tr></thead><tbody id="cat-body"></tbody></table></div>`;
  const label = { connected: 'connected', static: 'static', credentials: 'needs credentials', planned: 'planned' };
  const draw = () => {
    const q = $('cat-q').value.toLowerCase(), c = $('cat-c').value;
    $('cat-body').innerHTML = cat.filter(d => (!c || d.category === c) && (!q || JSON.stringify(d).toLowerCase().includes(q))).map(d =>
      `<tr><td><b>${d.name}</b></td><td><span class="status ${d.status}">${label[d.status]}</span></td><td>${d.category}</td><td>${d.provider}</td><td>${d.purpose}</td><td>${d.coverage}</td><td>${d.spatial}<br><small class="muted">${d.temporal}</small></td><td>${d.period}</td><td>${d.update}</td><td>${d.access}</td><td>${d.license}</td><td>${d.notes}</td></tr>`).join('');
  };
  $('cat-q').oninput = draw;
  $('cat-c').onchange = draw;
  draw();
}

export function renderAbout() {
  $('page-about').innerHTML = `<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
    <canvas data-logo width="150" height="150" style="width:150px;height:150px" role="img" aria-label="KPSTerra logo"></canvas><div><h1 style="margin:0;font-size:40px">About <span class="wordmark"><span class="wm-kps">KPS</span><span class="wm-terra">Terra</span></span></h1><p class="muted" style="margin:4px 0 0;font-size:16px">KPS + Earth</p></div></div>
  <p class="lead"><b>KPS + Earth.</b> An open, research-oriented platform for Earth observation, climate, water and fire, built by <b>Katroth Premsingh</b>. Fire is the first module: live satellite detections, orbits, long-term statistics, climate–fire analysis and fire-spread simulation for India.</p>
  <div class="grid2">
    <div class="box"><h3>What works now</h3><ul>
      <li>Live NASA FIRMS detections (VIIRS NOAA-20/21, Suomi-NPP, MODIS): filters, popups, time slider, CSV/GeoJSON export</li>
      <li>Globe, 2D and 3D-tilt views; dark, Esri imagery and NASA GIBS basemaps</li>
      <li>Satellite positions and ground tracks from CelesTrak elements (SGP4) for 9 Earth-observation satellites</li>
      <li>MODIS 2000–2026 India archive: state statistics, trends, seasonality, FRP, 0.25° density columns</li>
      <li>Custom-polygon statistics (needs the backend)</li>
      <li>Climate–Fire Explorer: ERA5-Land and IMD versus fire, with lagged correlation, regression and correlation maps</li>
    </ul></div>
    <div class="box"><h3>Important limitations</h3><ul>
      <li>A detection is a hot pixel seen by a satellite. It is not a confirmed fire incident, and counts are not burned area.</li>
      <li>Detection counts depend on overpass timing, cloud and smoke cover, and sensor. MODIS Terra/Aqua orbits have drifted since 2022–23, which affects recent trends.</li>
      <li>Satellite positions are estimates from orbital elements, not telemetry. KPSTerra does not know whether an instrument is imaging.</li>
      <li>Official fire status (fire of note, under control, …) is not shown: no authoritative incident feed for India is connected.</li>
      <li>Statistical associations do not imply causation.</li>
    </ul></div>
    <div class="box"><h3>Attribution</h3><p>Fire data: NASA FIRMS (LANCE/EOSDIS). Orbital elements: CelesTrak. Imagery: NASA GIBS/Worldview; Esri World Imagery. Basemap: © OpenStreetMap contributors, © CARTO. Boundaries: Survey of India via NWIC. Libraries: MapLibre GL JS, satellite.js, Apache ECharts, FastAPI, sgp4. Logo: Earth from NASA Blue Marble Next Generation (NASA Earth Observatory, public domain) with India's MODIS fire hotspots 2001–2026; the flame and the orbiting satellite are rendered by KPSTerra (backend/scripts/make_logo.py).</p></div>
    <div class="box"><h3>Methods</h3><p>Historical statistics use MODIS Collection 6.1 detections of type 0 (presumed vegetation fire), assigned to states by point-in-polygon. Trends: Mann–Kendall test with tie-corrected variance and Sen's slope on complete years. Anomalies are relative to the mean for 2001–2020. Hotspot classes on the density layer: low &lt;10, medium 10–50, high &gt;50 detections per 0.25° cell per year.</p></div>
  </div>`;
}
