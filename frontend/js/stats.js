// Statistics panel: summary cards + ECharts time series, seasonality, anomalies and FRP distribution.
import { MONTHS, download, fmt } from './config.js';

const charts = new Map();
const AXIS = { axisLine: { lineStyle: { color: '#475569' } }, axisLabel: { color: '#94a3b8', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.12)' } } };
const BASE = { backgroundColor: 'transparent', textStyle: { color: '#cbd5e1', fontFamily: 'Inter' }, animationDuration: 300,
  grid: { left: 48, right: 14, top: 30, bottom: 30 }, tooltip: { trigger: 'axis', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e5e7eb' } } };

export function chart(el, option) {
  charts.get(el)?.dispose();
  const c = echarts.init(el, null, { renderer: 'canvas' });
  c.setOption({ ...BASE, ...option });
  charts.set(el, c);
  return c;
}
window.addEventListener('resize', () => charts.forEach(c => c.resize()));

export function yearlyOption(s, title = 'Detections per year') {
  const last = s.years.length - 1;
  return {
    title: { text: title, textStyle: { fontSize: 12, color: '#cbd5e1' } },
    xAxis: { type: 'category', data: s.years, ...AXIS },
    yAxis: [{ type: 'value', ...AXIS }, { type: 'value', name: 'anomaly %', nameTextStyle: { color: '#94a3b8', fontSize: 10 }, ...AXIS, splitLine: { show: false } }],
    tooltip: { ...BASE.tooltip, valueFormatter: v => fmt(v, 1) },
    series: [
      { name: 'Detections', type: 'bar', data: s.yearly_count.map((v, i) => ({ value: v, itemStyle: { color: i === last ? '#64748b' : '#ff6b35' } })) },
      { name: `Anomaly vs ${s.baseline.join('–')} mean`, type: 'line', yAxisIndex: 1, data: s.anomaly_pct, symbolSize: 4, lineStyle: { color: '#38bdf8' }, itemStyle: { color: '#38bdf8' } },
    ],
  };
}

export function seasonOption(s) {
  return {
    title: { text: 'Seasonal cycle (mean detections per month)', textStyle: { fontSize: 12, color: '#cbd5e1' } },
    xAxis: { type: 'category', data: MONTHS, ...AXIS }, yAxis: { type: 'value', ...AXIS },
    series: [{ type: 'bar', data: s.climatology_mean_per_month, itemStyle: { color: '#ffa94d' } }],
  };
}

export function monthlyOption(s) {
  return {
    title: { text: 'Monthly detections', textStyle: { fontSize: 12, color: '#cbd5e1' } },
    grid: { ...BASE.grid, bottom: 52 },
    xAxis: { type: 'category', data: s.monthly_index, ...AXIS }, yAxis: { type: 'value', ...AXIS },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 6, textStyle: { color: '#94a3b8' }, borderColor: '#334155' }],
    series: [{ type: 'line', data: s.monthly_count, showSymbol: false, lineStyle: { width: 1.2, color: '#ff6b35' }, areaStyle: { color: 'rgba(255,107,53,.18)' } }],
  };
}

export function frpOption(s) {
  const e = s.frp.log10_edges;
  const labels = s.frp.log10_hist.map((_, i) => fmt(10 ** ((e[i] + e[i + 1]) / 2), 1));
  return {
    title: { text: 'FRP distribution (MW, log bins)', textStyle: { fontSize: 12, color: '#cbd5e1' } },
    xAxis: { type: 'category', data: labels, ...AXIS, axisLabel: { ...AXIS.axisLabel, interval: 4 } }, yAxis: { type: 'value', ...AXIS },
    series: [{ type: 'bar', data: s.frp.log10_hist, itemStyle: { color: '#e8233a' }, barCategoryGap: '5%' }],
  };
}

export function trendText(t) {
  if (!t || t.p == null) return 'insufficient data';
  return `${t.trend} (Sen slope ${t.sen_slope > 0 ? '+' : ''}${fmt(t.sen_slope, 0)} /yr, p = ${t.p < 0.001 ? '<0.001' : t.p.toFixed(3)}, ${t.years[0]}–${t.years[1]})`;
}

export function peakMonth(s) {
  const c = s.climatology_mean_per_month;
  return MONTHS[c.indexOf(Math.max(...c))];
}

export function renderStats(container, s, { title, product, params, extraTop = '' }) {
  if (!s || !s.n) {
    container.innerHTML = `${extraTop}<p class="muted">No detections in this area and period.</p>`;
    return;
  }
  const nYears = s.years.length;
  container.innerHTML = `${extraTop}
    <div class="cards">
      <div class="card"><div class="v">${fmt(s.n)}</div><div class="k">fire detections ${s.first_date.slice(0, 4)}–${s.last_date.slice(0, 4)}</div></div>
      <div class="card"><div class="v">${fmt(s.n / nYears)}</div><div class="k">mean detections / year</div></div>
      <div class="card"><div class="v">${peakMonth(s)}</div><div class="k">peak month</div></div>
      <div class="card"><div class="v">${fmt(s.frp.median, 1)}</div><div class="k">median FRP (MW)</div></div>
    </div>
    <p class="note"><b>Trend (Mann–Kendall):</b> ${trendText(s.trend)}. Last year shaded grey if incomplete; excluded from trend.</p>
    <div class="chart" data-c="yearly"></div>
    <div class="chart" data-c="season"></div>
    <div class="chart" data-c="monthly"></div>
    <div class="chart" data-c="frp"></div>
    <p class="note">Counts are satellite <b>detections</b> (${product}), not fire incidents or burned area. Detection counts depend on overpass times, cloud cover and sensor.</p>
    <div class="btns">
      <button class="btn" data-dl="yearly">⤓ Yearly CSV</button>
      <button class="btn" data-dl="monthly">⤓ Monthly CSV</button>
      <button class="btn" data-dl="params">⤓ Analysis parameters</button>
    </div>`;
  const q = k => container.querySelector(`[data-c="${k}"]`);
  chart(q('yearly'), yearlyOption(s));
  chart(q('season'), seasonOption(s));
  chart(q('monthly'), monthlyOption(s));
  chart(q('frp'), frpOption(s));
  const slug = title.replace(/[^a-z0-9]+/gi, '_').toLowerCase();
  container.querySelector('[data-dl="yearly"]').onclick = () => download(`${slug}_yearly.csv`,
    ['year,detections,frp_sum_mw,anomaly_pct', ...s.years.map((y, i) => `${y},${s.yearly_count[i]},${s.yearly_frp_sum_mw[i]},${s.anomaly_pct[i] ?? ''}`)].join('\n'));
  container.querySelector('[data-dl="monthly"]').onclick = () => download(`${slug}_monthly.csv`,
    ['month,detections', ...s.monthly_index.map((m, i) => `${m},${s.monthly_count[i]}`)].join('\n'));
  container.querySelector('[data-dl="params"]').onclick = () => download(`${slug}_parameters.json`, JSON.stringify({
    title, product, ...params, baseline: s.baseline, trend_method: 'Mann-Kendall (normal approx., tie-corrected variance) + Sen slope',
    generated_utc: new Date().toISOString(), app: 'KPSTerra 0.1.0' }, null, 2), 'application/json');
}
