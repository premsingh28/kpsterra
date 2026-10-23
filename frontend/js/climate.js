// Climate–Fire Explorer: interactive correlation, lag and regression analysis on state × month series.
import { download, fmt } from './config.js';
import { chart } from './stats.js';
import * as S from './climstats.js';

const $ = id => document.getElementById(id);
const SEASONS = {
  all: { label: 'All months', m: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] },
  fmam: { label: 'Fire season Feb–May', m: [2, 3, 4, 5] },
  mam: { label: 'Pre-monsoon Mar–May', m: [3, 4, 5] },
  jjas: { label: 'Monsoon Jun–Sep', m: [6, 7, 8, 9] },
  on: { label: 'Post-monsoon Oct–Nov', m: [10, 11] },
  djf: { label: 'Winter Jan–Feb + Dec', m: [12, 1, 2] },
};
const SUM_VARS = new Set(['imd_rain', 'tp']);
const AX = { axisLabel: { color: '#94a3b8', fontSize: 11 }, axisLine: { lineStyle: { color: '#475569' } }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.12)' } } };
const T = t => ({ text: t, textStyle: { fontSize: 12, color: '#cbd5e1' } });
let D = null, CORR = null, cmap = null, last = null;

const pfmt = p => (p == null ? '—' : p < 0.001 ? '<0.001' : p.toFixed(3));
const sigStar = p => (p == null ? '' : p < 0.01 ? '**' : p < 0.05 ? '*' : '');

export async function renderClimate() {
  const el = $('page-climate');
  el.innerHTML = '<p class="muted">Loading climate data…</p>';
  [D, CORR] = await Promise.all(['data/climate_state_monthly.json', 'data/climate_corr_grid.json'].map(u => fetch(u).then(r => r.json())));
  D.ym = D.months.map(s => [+s.slice(0, 4), +s.slice(5, 7)]);
  const regions = ['India', ...Object.keys(D.regions).filter(r => r !== 'India').sort()];
  const vopts = Object.entries(D.variables).map(([k, v]) => `<option value="${k}">${v.label} (${v.unit}) · ${k.startsWith('imd') ? 'IMD' : 'ERA5-Land'}</option>`).join('');
  el.innerHTML = `
  <h1>Climate–Fire Explorer</h1>
  <p class="lead">Test how fire activity relates to rainfall, temperature, humidity, soil moisture and vegetation in India, using your ERA5-Land and IMD data with MODIS detections for ${D.months[0]} to ${D.months.at(-1)}.</p>
  <p class="note" style="border-color:#f59e0b"><b>Association ≠ causation.</b> These are correlations between area-averaged monthly series. Shared seasonality, long-term trends and autocorrelation can create spurious associations. Use anomalies, detrending and the autocorrelation-adjusted p-value.</p>
  <div class="cf-layout">
    <div class="box cf-controls">
      <label>Study area<select id="cf-region">${regions.map(r => `<option>${r}</option>`).join('')}</select></label>
      <label>Fire metric<select id="cf-metric">
        <option value="log">Detections, log(1+n)</option><option value="count">Detections (count)</option><option value="frp">Mean FRP (MW)</option></select></label>
      <label>Environmental variable<select id="cf-var">${vopts}</select></label>
      <label>Months analysed<select id="cf-season">${Object.entries(SEASONS).map(([k, s]) => `<option value="${k}" ${k === 'fmam' ? 'selected' : ''}>${s.label}</option>`).join('')}</select></label>
      <label>Temporal aggregation<select id="cf-agg"><option value="monthly">Monthly values</option><option value="annual">One value per year (season total/mean)</option></select></label>
      <label>Lag: climate leads fire by <b id="cf-lag-v">0</b> months<input type="range" id="cf-lag" min="0" max="6" value="0"></label>
      <label class="chk"><input type="checkbox" id="cf-anom" checked> Remove seasonal cycle (monthly anomalies)</label>
      <label class="chk"><input type="checkbox" id="cf-detrend" checked> Remove linear trend</label>
      <label>Method<select id="cf-method"><option value="spearman">Spearman rank correlation</option><option value="pearson">Pearson correlation</option></select></label>
      <div class="btns"><button class="btn" id="cf-dl-data">⤓ Analysed data (CSV)</button><button class="btn" id="cf-dl-res">⤓ Results + parameters (JSON)</button></div>
    </div>
    <div class="cf-main">
      <div class="box" id="cf-result"></div>
      <div class="grid2" style="margin-top:12px">
        <div class="box"><div class="chart" id="cf-ts"></div></div>
        <div class="box"><div class="chart" id="cf-scatter"></div></div>
        <div class="box"><div class="chart" id="cf-lags"></div><p class="note">Bars: r at each lag. Solid bars have p<sub>adj</sub> &lt; 0.05 (autocorrelation-adjusted).</p></div>
        <div class="box"><div class="chart" id="cf-screen"></div><p class="note">Every variable under the same settings. Expect related variables (VPD, RH, temperature) to agree.</p></div>
      </div>
    </div>
  </div>

  <h2 style="margin:24px 0 6px">Multiple regression</h2>
  <p class="lead">Standardised predictors (z-scores), with the same region, months, lag and transforms as above. Coefficients show the change in the fire metric per 1 SD of each predictor, holding the others fixed.</p>
  <div class="box"><div class="chips" id="cf-reg-vars">${Object.entries(D.variables).map(([k, v]) => `<label><input type="checkbox" value="${k}" ${['vpd', 'imd_rain', 'swvl1'].includes(k) ? 'checked' : ''}> ${v.label}${k.startsWith('imd') ? ' (IMD)' : ''}</label>`).join('')}</div>
    <div id="cf-reg"></div></div>

  <h2 style="margin:24px 0 6px">Spatial correlation map</h2>
  <p class="lead">${CORR.method}</p>
  <div class="box"><label style="max-width:360px">Variable<select id="cf-map-var">${Object.keys(CORR.maps).map(k => `<option value="${k}">${D.variables[k].label}</option>`).join('')}</select></label>
    <div id="cf-map" style="height:520px;border-radius:8px;margin-top:8px"></div>
    <div class="ramp" style="max-width:420px;margin-top:8px"><span style="--c:#2166ac">−0.5</span><span style="--c:#67a9cf">−0.25</span><span style="--c:#f7f7f7">0</span><span style="--c:#ef8a62">+0.25</span><span style="--c:#b2182b">+0.5</span></div>
    <p class="note">Solid cells: significant after FDR correction. Faint cells: not significant. Grey: no data or too few fire months.</p></div>

  <div class="box" style="margin-top:16px"><h3>Data and methods</h3>
    <table><thead><tr><th>Variable</th><th>Source</th><th>Unit</th><th>Monthly aggregation</th></tr></thead><tbody>
    ${Object.entries(D.variables).map(([k, v]) => `<tr><td>${v.label}</td><td>${v.source}</td><td>${v.unit}</td><td>${v.aggregation}</td></tr>`).join('')}
    <tr><td>Fire</td><td>${D.fire_product}</td><td>detections, MW</td><td>monthly count; mean FRP of detections</td></tr></tbody></table>
    <p class="note">${D.method} Correlation p-values come from the t-test. p<sub>adj</sub> uses an effective sample size n<sub>eff</sub> = n(1−r₁r₂)/(1+r₁r₂) (Bretherton et al. 1999), where r₁ and r₂ are lag-1 autocorrelations. Missing values: pairs with a missing value in either series are dropped. Months with no detections have no mean FRP. Annual mode sums fire counts (and rainfall) over the selected months and averages the other variables; the lag shifts the climate window earlier.</p>
  </div>`;
  ['cf-region', 'cf-metric', 'cf-var', 'cf-season', 'cf-agg', 'cf-anom', 'cf-detrend', 'cf-method'].forEach(id => ($(id).onchange = update));
  $('cf-lag').oninput = () => { $('cf-lag-v').textContent = $('cf-lag').value; update(); };
  $('cf-reg-vars').onchange = update;
  $('cf-dl-data').onclick = dlData;
  $('cf-dl-res').onclick = dlResults;
  $('cf-map-var').onchange = drawMap;
  update();
  initMap();
}

function settings() {
  return { region: $('cf-region').value, metric: $('cf-metric').value, variable: $('cf-var').value, season: $('cf-season').value,
    agg: $('cf-agg').value, lag: +$('cf-lag').value, anomalies: $('cf-anom').checked, detrend: $('cf-detrend').checked, method: $('cf-method').value };
}

const nul = a => a.map(v => (v == null ? NaN : v));

function fireSeries(R, metric) {
  if (metric === 'frp') return nul(R.fire_frp_mean);
  return R.fire_count.map(v => (metric === 'log' ? Math.log1p(v) : v));
}

// Returns aligned {labels, f, v} after lag, aggregation, transforms and month selection.
export function prepare(s, variable = s.variable) {
  const R = D.regions[s.region];
  const months = D.ym.map(d => d[1]);
  let f = fireSeries(R, s.metric);
  let v = nul(R[variable]);
  const lagged = v.map((_, i) => (i - s.lag >= 0 ? v[i - s.lag] : NaN));
  const sel = SEASONS[s.season].m;
  if (s.agg === 'monthly') {
    let ff = f, vv = lagged;
    if (s.anomalies) { ff = S.deseasonalise(ff, months); vv = S.deseasonalise(vv, months); }
    if (s.detrend) { ff = S.detrend(ff); vv = S.detrend(vv); }
    const idx = months.map((m, i) => (sel.includes(m) ? i : -1)).filter(i => i >= 0);
    return { labels: idx.map(i => D.months[i]), f: idx.map(i => ff[i]), v: idx.map(i => vv[i]) };
  }
  // annual: one value per year over the selected months
  const counts = R.fire_count;
  const years = [...new Set(D.ym.map(d => d[0]))];
  const out = { labels: [], f: [], v: [] };
  for (const y of years) {
    const idx = D.ym.map((d, i) => (d[0] === y && sel.includes(d[1]) ? i : -1)).filter(i => i >= 0);
    if (idx.length < sel.length) continue;
    let fy;
    if (s.metric === 'frp') {
      let w = 0, sum = 0;
      idx.forEach(i => { const c = counts[i], m = R.fire_frp_mean[i]; if (c && m != null) { w += c; sum += c * m; } });
      fy = w ? sum / w : NaN;
    } else {
      const tot = idx.reduce((a, i) => a + counts[i], 0);
      fy = s.metric === 'log' ? Math.log1p(tot) : tot;
    }
    const vals = idx.map(i => lagged[i]);
    const vy = vals.some(Number.isNaN) ? NaN : SUM_VARS.has(variable) ? vals.reduce((a, b) => a + b, 0) : vals.reduce((a, b) => a + b, 0) / vals.length;
    out.labels.push(String(y)); out.f.push(fy); out.v.push(vy);
  }
  if (s.detrend) { out.f = S.detrend(out.f); out.v = S.detrend(out.v); }
  return out;
}

const metricLabel = s => ({ log: 'log(1+detections)', count: 'detections', frp: 'mean FRP (MW)' })[s.metric]
  + (s.agg === 'monthly' && s.anomalies ? ' anomaly' : '') + (s.detrend ? ', detrended' : '');

function update() {
  const s = settings();
  $('cf-anom').disabled = s.agg === 'annual';
  const V = D.variables[s.variable];
  const d = prepare(s);
  const c = S.correlate(d.v, d.f, s.method);
  const lags = Array.from({ length: 7 }, (_, L) => S.correlate(...(p => [p.v, p.f])(prepare({ ...s, lag: L })), s.method));
  const screen = Object.keys(D.variables).map(k => ({ k, ...S.correlate(...(p => [p.v, p.f])(prepare(s, k)), s.method) }));
  last = { settings: s, data: d, result: c, lags, screen };

  const nPairs = c.n, period = d.labels.length ? `${d.labels[0]} – ${d.labels.at(-1)}` : '—';
  const noVar = D.regions[s.region][s.variable].every(v => v == null);
  const verdict = noVar ? `No ${V.source.split(' ')[0]} grid cell centre lies inside ${s.region}, so this variable is unavailable here. Try the ERA5-Land equivalent (0.1°).` :
    c.r == null ? 'Not enough data.' :
    `${Math.abs(c.r) < 0.1 ? 'Negligible' : Math.abs(c.r) < 0.3 ? 'Weak' : Math.abs(c.r) < 0.5 ? 'Moderate' : 'Strong'} ${c.r > 0 ? 'positive' : 'negative'} association; ` +
    (c.p_adj < 0.05 ? 'significant after the autocorrelation adjustment.' : c.p < 0.05 ? 'nominally significant, but <b>not</b> after the autocorrelation adjustment.' : 'not statistically significant.');
  $('cf-result').innerHTML = `
    <div class="cards" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">
      <div class="card"><div class="v">${c.r == null ? '—' : (c.r > 0 ? '+' : '') + c.r.toFixed(3)}${sigStar(c.p_adj)}</div><div class="k">${s.method === 'spearman' ? 'Spearman ρ' : 'Pearson r'}</div></div>
      <div class="card"><div class="v">${pfmt(c.p)}</div><div class="k">p (n = ${nPairs})</div></div>
      <div class="card"><div class="v">${pfmt(c.p_adj)}</div><div class="k">p<sub>adj</sub> (n<sub>eff</sub> ≈ ${fmt(c.n_eff, 0)})</div></div>
      <div class="card"><div class="v">${s.lag} mo</div><div class="k">lag (climate leads)</div></div>
    </div>
    <p style="margin:6px 0"><b>${verdict}</b></p>
    <dl class="kv"><dt>Study area</dt><dd>${s.region}</dd><dt>Period</dt><dd>${period} · ${SEASONS[s.season].label} · ${s.agg === 'monthly' ? 'monthly' : 'annual season values'}</dd>
    <dt>Fire metric</dt><dd>${metricLabel(s)}</dd><dt>Variable</dt><dd>${V.label} (${V.unit}). ${V.source}</dd>
    <dt>Missing data</dt><dd>${d.labels.length - nPairs} of ${d.labels.length} ${s.agg === 'monthly' ? 'months' : 'years'} dropped (missing in either series)</dd></dl>`;

  const vName = `${V.label}${s.agg === 'monthly' && s.anomalies ? ' anomaly' : ''}`;
  chart($('cf-ts'), {
    title: T('Analysed series'), legend: { textStyle: { color: '#cbd5e1' }, top: 18 }, grid: { left: 52, right: 52, top: 54, bottom: 50 },
    tooltip: { trigger: 'axis', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e5e7eb' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 6, borderColor: '#334155' }],
    xAxis: { type: 'category', data: d.labels, ...AX },
    yAxis: [{ type: 'value', ...AX, name: 'fire', nameTextStyle: { color: '#94a3b8' } }, { type: 'value', ...AX, splitLine: { show: false }, name: V.unit, nameTextStyle: { color: '#94a3b8' } }],
    series: [
      { name: metricLabel(s), type: 'line', data: d.f.map(x => (Number.isNaN(x) ? null : x)), showSymbol: s.agg !== 'monthly', lineStyle: { color: '#ff6b35' }, itemStyle: { color: '#ff6b35' } },
      { name: vName, type: 'line', yAxisIndex: 1, data: d.v.map(x => (Number.isNaN(x) ? null : x)), showSymbol: s.agg !== 'monthly', lineStyle: { color: '#38bdf8' }, itemStyle: { color: '#38bdf8' } },
    ],
  });

  const pts = d.v.map((x, i) => [x, d.f[i], d.labels[i]]).filter(p => !Number.isNaN(p[0]) && !Number.isNaN(p[1]));
  const lin = pts.length > 3 ? S.ols(pts.map(p => p[1]), [pts.map(p => p[0])], ['x']) : null;
  const xs = pts.map(p => p[0]);
  const line = lin?.coef ? [Math.min(...xs), Math.max(...xs)].map(x => [x, lin.coef[0].b + lin.coef[1].b * x]) : [];
  chart($('cf-scatter'), {
    title: T(lin?.coef ? `Linear fit: slope ${lin.coef[1].b.toPrecision(3)} ± ${lin.coef[1].se.toPrecision(2)} (SE), R² = ${lin.r2.toFixed(3)}` : 'Scatter'),
    grid: { left: 52, right: 16, top: 34, bottom: 40 },
    tooltip: { trigger: 'item', formatter: p => (p.data[2] ? `${p.data[2]}<br>${V.label}: ${fmt(p.data[0], 2)}<br>fire: ${fmt(p.data[1], 2)}` : ''), backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e5e7eb' } },
    xAxis: { type: 'value', name: vName, nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: '#94a3b8' }, scale: true, ...AX },
    yAxis: { type: 'value', name: 'fire', nameTextStyle: { color: '#94a3b8' }, scale: true, ...AX },
    series: [{ type: 'scatter', data: pts, symbolSize: 5, itemStyle: { color: 'rgba(255,107,53,.6)' } },
      { type: 'line', data: line, showSymbol: false, lineStyle: { color: '#38bdf8', width: 2 }, tooltip: { show: false } }],
  });

  chart($('cf-lags'), {
    title: T(`Lagged correlation: ${V.label} leads fire`), grid: { left: 44, right: 16, top: 34, bottom: 34 },
    xAxis: { type: 'category', data: lags.map((_, i) => `${i} mo`), ...AX }, yAxis: { type: 'value', min: -1, max: 1, ...AX },
    tooltip: { trigger: 'axis', formatter: p => { const l = lags[p[0].dataIndex]; return `lag ${p[0].dataIndex}: r = ${l.r?.toFixed(3)}<br>p = ${pfmt(l.p)}, p<sub>adj</sub> = ${pfmt(l.p_adj)}<br>n = ${l.n}`; }, backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e5e7eb' } },
    series: [{ type: 'bar', data: lags.map((l, i) => ({ value: l.r, itemStyle: { color: (l.r ?? 0) > 0 ? '#ff6b35' : '#38bdf8', opacity: l.p_adj < 0.05 ? 1 : 0.3, borderColor: i === s.lag ? '#fff' : 'transparent', borderWidth: 1.5 } })) }],
  });

  const sc = [...screen].sort((a, b) => (a.r ?? 0) - (b.r ?? 0));
  chart($('cf-screen'), {
    title: T(`All variables at lag ${s.lag}`), grid: { left: 170, right: 20, top: 34, bottom: 26 },
    xAxis: { type: 'value', min: -1, max: 1, ...AX }, yAxis: { type: 'category', data: sc.map(x => D.variables[x.k].label + (x.k.startsWith('imd') ? ' (IMD)' : '')), axisLabel: { color: '#cbd5e1', fontSize: 11 } },
    tooltip: { trigger: 'axis', formatter: p => { const x = sc[p[0].dataIndex]; return `${D.variables[x.k].label}: r = ${x.r?.toFixed(3) ?? '—'}<br>p<sub>adj</sub> = ${pfmt(x.p_adj)}, n = ${x.n}`; }, backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e5e7eb' } },
    series: [{ type: 'bar', data: sc.map(x => ({ value: x.r, itemStyle: { color: (x.r ?? 0) > 0 ? '#ff6b35' : '#38bdf8', opacity: x.p_adj < 0.05 ? 1 : 0.3 } })) }],
  });

  updateRegression(s);
}

const z = a => {
  const ok = a.filter(v => !Number.isNaN(v));
  const m = ok.reduce((x, y) => x + y, 0) / ok.length;
  const sd = Math.sqrt(ok.reduce((x, y) => x + (y - m) ** 2, 0) / (ok.length - 1));
  return a.map(v => (v - m) / sd);
};

function updateRegression(s) {
  const vars = [...document.querySelectorAll('#cf-reg-vars input:checked')].map(i => i.value);
  const box = $('cf-reg');
  if (!vars.length) { box.innerHTML = '<p class="muted">Select at least one predictor.</p>'; return; }
  const preps = vars.map(k => prepare(s, k));
  let r;
  try { r = S.ols(preps[0].f, preps.map(p => z(p.v)), vars); } catch (e) { box.innerHTML = `<p style="color:#f87171">${e.message}</p>`; return; }
  last.regression = { predictors: vars, ...r };
  if (r.error) { box.innerHTML = `<p class="muted">${r.error} (n = ${r.n}).</p>`; return; }
  const warn = [];
  if (r.coef.some(c => c.vif > 5)) warn.push('VIF &gt; 5: predictors are strongly collinear, so individual coefficients are unstable (e.g. VPD with RH or temperature).');
  if (r.durbin_watson < 1.5 || r.durbin_watson > 2.5) warn.push(`Durbin–Watson = ${r.durbin_watson.toFixed(2)}: residuals are autocorrelated, so p-values are optimistic.`);
  box.innerHTML = `<div class="cards" style="grid-template-columns:repeat(4,minmax(110px,1fr))">
    <div class="card"><div class="v">${r.r2.toFixed(3)}</div><div class="k">R²</div></div><div class="card"><div class="v">${r.adj_r2.toFixed(3)}</div><div class="k">adjusted R²</div></div>
    <div class="card"><div class="v">${r.n}</div><div class="k">observations</div></div><div class="card"><div class="v">${r.durbin_watson.toFixed(2)}</div><div class="k">Durbin–Watson</div></div></div>
    <div style="overflow-x:auto"><table><thead><tr><th>Term</th><th>β (per 1 SD)</th><th>SE</th><th>t</th><th>p</th><th>VIF</th></tr></thead><tbody>
    ${r.coef.map(c => `<tr><td>${c.name === 'intercept' ? 'Intercept' : D.variables[c.name].label}</td><td>${c.b.toFixed(4)}${sigStar(c.p)}</td><td>${c.se.toFixed(4)}</td><td>${c.t.toFixed(2)}</td><td>${pfmt(c.p)}</td><td>${c.vif == null ? '' : c.vif.toFixed(2)}</td></tr>`).join('')}
    </tbody></table></div>
    ${warn.map(w => `<p class="note" style="border-color:#f59e0b">${w}</p>`).join('')}
    <p class="note">Response: ${metricLabel(s)}, ${s.region}, ${SEASONS[s.season].label}, lag ${s.lag} months. Listwise deletion of incomplete rows. * p&lt;0.05, ** p&lt;0.01 (OLS; not adjusted for autocorrelation).</p>`;
}

function dlData() {
  const { settings: s, data: d } = last;
  download(`climate_fire_${s.region}_${s.variable}.csv`.replace(/\s+/g, '_'),
    [`period,fire_${s.metric},${s.variable}_lag${s.lag}`, ...d.labels.map((l, i) => `${l},${Number.isNaN(d.f[i]) ? '' : d.f[i]},${Number.isNaN(d.v[i]) ? '' : d.v[i]}`)].join('\n'));
}

function dlResults() {
  const { settings: s, result, lags, screen, regression } = last;
  const strip = c => ({ r: c.r, p: c.p, n: c.n, n_eff: c.n_eff, p_adj: c.p_adj });
  download('climate_fire_results.json', JSON.stringify({
    app: 'KPSTerra Climate–Fire Explorer', generated_utc: new Date().toISOString(), parameters: { ...s, months: SEASONS[s.season].m },
    data: { climate_file: 'data/climate_state_monthly.json', generated_utc: D.generated_utc, fire_product: D.fire_product, variable: D.variables[s.variable], aggregation_method: D.method },
    correlation: strip(result), lagged: lags.map((l, i) => ({ lag: i, ...strip(l) })), all_variables: screen.map(x => ({ variable: x.k, ...strip(x) })), regression,
    caveat: 'Statistical association does not establish causation.',
  }, null, 2), 'application/json');
}

// ---------- correlation map ----------
function initMap() {
  cmap = new maplibregl.Map({
    container: 'cf-map', center: [80, 22], zoom: 3.6, attributionControl: { compact: true },
    style: { version: 8, sources: { b: { type: 'raster', tileSize: 256, attribution: 'Basemap © Esri',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'] } },
    layers: [{ id: 'b', type: 'raster', source: 'b' }] },
  });
  cmap.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  cmap.once('style.load', () => {
    cmap.addSource('cells', { type: 'geojson', data: cellsGeoJSON($('cf-map-var').value) });
    cmap.addLayer({ id: 'cells', type: 'fill', source: 'cells', paint: {
      'fill-color': ['interpolate', ['linear'], ['get', 'r'], -0.5, '#2166ac', -0.25, '#67a9cf', 0, '#f7f7f7', 0.25, '#ef8a62', 0.5, '#b2182b'],
      'fill-opacity': ['case', ['==', ['get', 's'], 1], 0.85, 0.22] } });
    cmap.addSource('st', { type: 'geojson', data: 'data/states.geojson' });
    cmap.addLayer({ id: 'st', type: 'line', source: 'st', paint: { 'line-color': '#cbd5e1', 'line-width': 0.6, 'line-opacity': 0.7 } });
    cmap.on('click', 'cells', e => {
      const p = e.features[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`Spearman r = <b>${(+p.r).toFixed(2)}</b><br>${p.s ? 'significant (FDR q = 0.05)' : 'not significant'}<br><small>cell ${p.lat}°N, ${p.lon}°E</small>`).addTo(cmap);
    });
  });
}

function cellsGeoJSON(key) {
  const d = CORR.cell_deg;
  return { type: 'FeatureCollection', features: CORR.maps[key].map(([j, i, r, s]) => {
    const y = CORR.lat0 + j * d, x = CORR.lon0 + i * d;
    return { type: 'Feature', properties: { r, s, lat: y, lon: x }, geometry: { type: 'Polygon', coordinates: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]] } };
  }) };
}

function drawMap() {
  cmap.getSource('cells')?.setData(cellsGeoJSON($('cf-map-var').value));
}

export const resizeClimate = () => cmap?.resize();
