// Where the FastAPI backend lives. Default: the same site that served this page (local server or the
// Hugging Face Space). A static copy elsewhere (e.g. GitHub Pages) sets window.KPSTERRA_API or ?api=https://...
export const API = (() => {
  const q = new URLSearchParams(location.search).get('api');
  if (q) return q.replace(/\/$/, '');
  if (window.KPSTERRA_API !== undefined) return window.KPSTERRA_API.replace(/\/$/, '');
  if (location.protocol === 'file:') return 'http://localhost:8000';
  return '';
})();

// Hotspot activity classes for the 0.25° density layer (detections per cell per year).
// Documented in the legend and README; change here to re-classify.
export const ACTIVITY = { medium: 10, high: 50 };
// Hotspot-cluster activity classes for live detections (detections grouped in one display cluster).
export const CLUSTER_ACTIVITY = { medium: 10, high: 50 };
export const ACTIVITY_COLORS = { low: '#ffd166', medium: '#ff7b00', high: '#d00000' };

export const FRP_STEPS = ['#ffe066', 5, '#ffa94d', 20, '#ff6b35', 50, '#e8233a', 100, '#b5179e'];

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export async function getJSON(url, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout ?? 60000);
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)) : `HTTP ${r.status}`);
    return body;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('request timed out');
    if (e instanceof TypeError) throw new Error('backend not reachable');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export function toast(msg, err = false, ms = 4500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add('hidden'), ms);
}

export function download(name, text, type = 'text/csv') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export const fmt = (n, d = 0) => n == null || Number.isNaN(n) ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d });
