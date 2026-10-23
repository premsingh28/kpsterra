// Map legend, generated from the same constants and icons the layers use.
import { ACTIVITY, ACTIVITY_COLORS, CLUSTER_ACTIVITY } from './config.js';
import { STATUS, gdacsIcon } from './layers.js';
import { SENSORS } from './satellites.js';

const sw = (c, round = false) => `<i class="sw" style="background:${c}${round ? ';border-radius:50%' : ''}"></i>`;
const line = (c, dash = false) => `<i class="lg-line" style="border-top:3px ${dash ? 'dashed' : 'solid'} ${c}"></i>`;
const icon = (t, a) => {
  const img = gdacsIcon(t, a, 44);
  const c = document.createElement('canvas');
  c.width = c.height = 44;
  c.getContext('2d').putImageData(img, 0, 0);
  return `<img src="${c.toDataURL()}" width="20" height="20" alt="" class="lg-icon">`;
};
const sec = (title, body, open = false) => `<details class="lg" ${open ? 'open' : ''}><summary>${title}</summary>${body}</details>`;

export function renderLegend() {
  const el = document.getElementById('legend');
  el.innerHTML = `<div class="panel-head lg-head"><h2>Map legend</h2><button class="icon-btn x" data-close="legend" aria-label="Close">✕</button></div>` +
  sec('Authoritative fire status', `
    <p>${sw('#ff2d55')}Fire of Note: <span class="muted">not shown (no source connected)</span></p>
    ${Object.values(STATUS).map(s => `<p>${sw(s.color)}${s.label}</p>`).join('')}
    <p class="muted">Agency-reported status for USA (NIFC) and Canada (CWFIS) only. India has no public incident feed. Status is never inferred from satellite detections.</p>`, true) +
  sec('Satellite fire detections', `
    <div class="ramp"><span style="--c:#ffe066">&lt;5</span><span style="--c:#ffa94d">5–20</span><span style="--c:#ff6b35">20–50</span><span style="--c:#e8233a">50–100</span><span style="--c:#b5179e">&gt;100</span></div>
    <p class="muted" style="margin-top:2px">Colour = fire radiative power (MW)</p>
    <p><span class="age-demo"><i style="width:11px;height:11px;opacity:1"></i><i style="width:8px;height:8px;opacity:.7"></i><i style="width:6px;height:6px;opacity:.45"></i></span> Newer → older</p>
    <p class="muted">Dots fade and shrink as a detection ages. Fading shows elapsed time only, not that the fire is out. Each dot is a thermal anomaly in one satellite pixel, not a verified incident.</p>`, true) +
  sec('Hotspot clusters', `
    <p>${sw(ACTIVITY_COLORS.high, true)}High activity: ≥ ${CLUSTER_ACTIVITY.high} detections</p>
    <p>${sw(ACTIVITY_COLORS.medium, true)}Medium activity: ${CLUSTER_ACTIVITY.medium}–${CLUSTER_ACTIVITY.high - 1}</p>
    <p>${sw(ACTIVITY_COLORS.low, true)}Low activity: &lt; ${CLUSTER_ACTIVITY.medium}</p>
    <p class="muted">Display grouping at the current zoom ("Hotspot clusters" display mode). Thresholds are set in js/config.js. A cluster is not a fire event.</p>`) +
  sec('Fire density 2001–2026', `
    <p>${sw('#d00000')}High: &gt; ${ACTIVITY.high} · ${sw('#ff7b00')}Medium: ${ACTIVITY.medium}–${ACTIVITY.high} · ${sw('#ffd166')}Low: &lt; ${ACTIVITY.medium}</p>
    <p class="muted">MODIS detections per 0.25° cell per year. Column height ∝ √count.</p>`) +
  sec('Satellite tracks', `
    ${Object.values(SENSORS).map(s => `<p>${sw(s.color, true)}${s.label}</p>`).join('')}
    <p>${line('#38bdf8', true)}Ground track for the next 12 h: tap a satellite</p>
    <p>${line('rgba(56,189,248,.35)', true)}Last 50 min</p>
    <p class="muted">Colours show the sensor, not the track. A faded Landsat icon means it is over the night side (OLI images in daylight only). Positions are SGP4 estimates from CelesTrak elements, not telemetry.</p>`) +
  sec('Tropical cyclone tracks (GDACS)', `
    <p>${line('#ef4444')}Red alert · ${line('#f97316')}Orange · ${line('#7dd3fc')}Green</p>
    <p>${icon('TC', 'Red')} Storm position (alert colour)</p>
    <p class="muted">GDACS reports alert levels; Saffir–Simpson categories are not included in this feed.</p>`) +
  sec('Wind', `
    <p><i class="lg-line" style="border-top:2px solid #e0f2fe;width:30px"></i> Strong: long, bright streak</p>
    <p><i class="lg-line" style="border-top:1px solid rgba(255,255,255,.5);width:12px"></i> Light: short, faint</p>
    <p class="muted">Streaks move the way the wind blows. NOAA GFS 10 m analysis at 1° (~110 km), so local gusts and terrain effects are smoothed out.</p>`) +
  sec('Disaster alerts (GDACS)', `
    <p>${icon('EQ', 'Green')} Earthquake ${icon('FL', 'Orange')} Flood ${icon('TC', 'Red')} Cyclone</p>
    <p>${icon('VO', 'Green')} Volcano ${icon('DR', 'Orange')} Drought ${icon('WF', 'Green')} Wildfire</p>
    <p>Outline = alert level: ${sw('#22c55e')}Green ${sw('#f97316')}Orange ${sw('#ef4444')}Red</p>`) +
  sec('Clouds, smoke and aerosol', `
    <p><b>Himawari IR (Band 13):</b> colder, higher cloud tops are brighter or coloured; deep convection (storms) appears red or black.</p>
    <p><b>OMPS UV aerosol index:</b> higher values (darker orange or brown) mean absorbing smoke or dust. This is a column satellite retrieval, not surface PM2.5.</p>
    <p><b>MAIAC aerosol optical depth:</b> total-column haze, 0 (clear) to &gt;1 (very hazy). Daily, cloud-free pixels only.</p>`) +
  sec('Not yet available', `
    <p class="muted"><b>Energy infrastructure:</b> needs an OpenStreetMap power/pipeline extract served by KPSTerra. Open Infrastructure Map tiles are not licensed for reuse.</p>
    <p class="muted"><b>Hourly smoke plume (surface PM2.5):</b> NOAA HRRR-Smoke covers North America only. For India, CAMS forecasts need an ADS account (planned).</p>
    <p class="muted"><b>Burned area:</b> MODIS MCD64A1 (planned).</p>`);
  el.querySelector('[data-close]').onclick = () => {
    el.hidden = true;
    document.querySelector('.rail [data-pop="legend"]')?.classList.remove('active');
  };
}
