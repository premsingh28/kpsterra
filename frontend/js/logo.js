// Animated KPSTerra logo: realistic globe (pre-rendered), orbit path and a satellite revolving around Earth.
// Layers come from backend/scripts/make_logo.py. Falls back to a still frame for prefers-reduced-motion.
const load = src => new Promise((ok, err) => { const i = new Image(); i.onload = () => ok(i); i.onerror = err; i.src = src; });
let assets = null;

async function getAssets() {
  assets ??= Promise.all([
    load('assets/kpsterra-globe.png'), load('assets/kpsterra-satellite.png'),
    fetch('assets/kpsterra-logo-geom.json').then(r => r.json()),
  ]);
  return assets;
}

const PERIOD_MS = 9000;
const STILL_ANGLE = 35 * Math.PI / 180;

export async function mountLogo(canvas) {
  let globe, sat, g;
  try { [globe, sat, g] = await getAssets(); } catch { return; }
  const css = canvas.clientWidth || +canvas.getAttribute('width');
  const dpr = devicePixelRatio || 1;
  const C = Math.round(css * dpr);
  canvas.width = canvas.height = C;
  const ctx = canvas.getContext('2d');
  const rx = g.rx * C, ry = g.ry * C, tilt = g.tilt * Math.PI / 180;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const ring = (a0, a1, alpha, width) => {
    ctx.beginPath();
    ctx.ellipse(C / 2, C / 2, rx, ry, tilt, a0, a1);
    ctx.strokeStyle = `rgba(170,220,255,${alpha})`;
    ctx.lineWidth = Math.max(0.8, width * C);
    ctx.stroke();
  };
  const satellite = t => {
    const x = rx * Math.cos(t), y = ry * Math.sin(t);
    const px = C / 2 + x * Math.cos(tilt) - y * Math.sin(tilt);
    const py = C / 2 + x * Math.sin(tilt) + y * Math.cos(tilt);
    const front = Math.sin(t) > 0;
    const s = g.satellite_size * C * (0.82 + 0.18 * (Math.sin(t) + 1) / 2);   // slightly smaller when far side
    ctx.globalAlpha = front ? 1 : 0.85;
    ctx.drawImage(sat, px - s / 2, py - s / 2, s, s);
    ctx.globalAlpha = 1;
  };

  const frame = now => {
    const t = still ? STILL_ANGLE : (now / PERIOD_MS) * 2 * Math.PI;
    const front = Math.sin(t) > 0;
    ctx.clearRect(0, 0, C, C);
    ring(Math.PI, 2 * Math.PI, 0.22, 0.0035);          // far half of the orbit
    if (!front) satellite(t);                            // satellite behind Earth
    ctx.drawImage(globe, 0, 0, C, C);
    ring(0, Math.PI, 0.55, 0.0045);                      // near half of the orbit
    if (front) satellite(t);
    if (!still) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

export function mountAll(root = document) {
  root.querySelectorAll('canvas[data-logo]').forEach(c => { if (!c.dataset.mounted) { c.dataset.mounted = 1; mountLogo(c); } });
}
