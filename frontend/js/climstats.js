// Browser port of backend/app/services/climate.py. Verified against scipy by tests/climstats.html.

const isNum = v => v != null && !Number.isNaN(v);
const mean = a => a.reduce((s, v) => s + v, 0) / a.length;

// --- distributions -------------------------------------------------------
function lgamma(x) {
  const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let y = x, t = x + 5.5;
  t -= (x + 0.5) * Math.log(t);
  let s = 1.000000000190015;
  for (const ci of c) s += ci / ++y;
  return -t + Math.log(2.5066282746310005 * s / x);
}
function betacf(a, b, x) {
  const EPS = 3e-14, FPMIN = 1e-300;
  let qab = a + b, qap = a + 1, qam = a - 1, c = 1, d = 1 - qab * x / qap;
  if (Math.abs(d) < FPMIN) d = FPMIN;
  d = 1 / d;
  let h = d;
  for (let m = 1; m <= 300; m++) {
    const m2 = 2 * m;
    let aa = m * (b - m) * x / ((qam + m2) * (a + m2));
    d = 1 + aa * d; if (Math.abs(d) < FPMIN) d = FPMIN;
    c = 1 + aa / c; if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d; h *= d * c;
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
    d = 1 + aa * d; if (Math.abs(d) < FPMIN) d = FPMIN;
    c = 1 + aa / c; if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < EPS) break;
  }
  return h;
}
export function ibeta(x, a, b) {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const bt = Math.exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * Math.log(x) + b * Math.log(1 - x));
  return x < (a + 1) / (a + b + 2) ? bt * betacf(a, b, x) / a : 1 - bt * betacf(b, a, 1 - x) / b;
}
// two-sided p for Student t with df degrees of freedom
export const tTwoSided = (t, df) => ibeta(df / (df + t * t), df / 2, 0.5);

export function rPvalue(r, n) {
  if (Math.abs(r) >= 1) return 0;
  return tTwoSided(r * Math.sqrt((n - 2) / (1 - r * r)), n - 2);
}

// --- transforms ----------------------------------------------------------
export function ranks(a) {
  const idx = a.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]);
  const r = new Array(a.length);
  for (let i = 0; i < idx.length;) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
    for (let k = i; k <= j; k++) r[idx[k][1]] = (i + j) / 2 + 1;
    i = j + 1;
  }
  return r;
}

export function deseasonalise(values, months, standardise = false) {
  const v = values.map(x => (isNum(x) ? x : NaN));
  for (let m = 1; m <= 12; m++) {
    const ix = months.map((mm, i) => (mm === m && isNum(v[i]) ? i : -1)).filter(i => i >= 0);
    if (!ix.length) continue;
    const mu = mean(ix.map(i => v[i]));
    ix.forEach(i => (v[i] -= mu));
    if (standardise) {
      const sd = ix.length > 1 ? Math.sqrt(ix.reduce((s, i) => s + v[i] ** 2, 0) / (ix.length - 1)) : 0;
      ix.forEach(i => (v[i] = sd > 0 ? v[i] / sd : NaN));
    }
  }
  return v;
}

export function detrend(values) {
  const pts = values.map((v, i) => [i, v]).filter(p => isNum(p[1]));
  if (pts.length < 3) return values.slice();
  const mx = mean(pts.map(p => p[0])), my = mean(pts.map(p => p[1]));
  const b = pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  return values.map((v, i) => (isNum(v) ? v - (my + b * (i - mx)) : NaN));
}

function lag1(v) {
  const m = mean(v);
  let num = 0, den = 0;
  v.forEach((x, i) => { den += (x - m) ** 2; if (i) num += (x - m) * (v[i - 1] - m); });
  return den > 0 ? num / den : 0;
}

function pearsonR(x, y) {
  const mx = mean(x), my = mean(y);
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < x.length; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; }
  return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : NaN;
}

// r, p, n, effective n (Bretherton et al. 1999) and autocorrelation-adjusted p
export function correlate(xs, ys, method = 'pearson') {
  let x = [], y = [];
  xs.forEach((v, i) => { if (isNum(v) && isNum(ys[i])) { x.push(v); y.push(ys[i]); } });
  const n = x.length;
  if (n < 4) return { r: null, p: null, n, n_eff: null, p_adj: null };
  if (method === 'spearman') { x = ranks(x); y = ranks(y); }
  const r = pearsonR(x, y);
  if (!isNum(r)) return { r: null, p: null, n, n_eff: null, p_adj: null };
  const r1 = lag1(x), r2 = lag1(y);
  const nEff = Math.max(3, Math.min(n, n * (1 - r1 * r2) / (1 + r1 * r2)));
  return { r, p: rPvalue(r, n), n, n_eff: nEff, p_adj: rPvalue(r, nEff), x, y };
}

// --- regression ----------------------------------------------------------
function invert(M) {
  const n = M.length, A = M.map((row, i) => [...row, ...Array.from({ length: n }, (_, j) => (i === j ? 1 : 0))]);
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < 1e-12) throw new Error('singular matrix (collinear predictors)');
    [A[c], A[p]] = [A[p], A[c]];
    const d = A[c][c];
    for (let j = 0; j < 2 * n; j++) A[c][j] /= d;
    for (let r = 0; r < n; r++) if (r !== c) { const f = A[r][c]; for (let j = 0; j < 2 * n; j++) A[r][j] -= f * A[c][j]; }
  }
  return A.map(row => row.slice(n));
}

function fit(y, X) {   // X rows already include intercept column
  const k = X[0].length;
  const XtX = Array.from({ length: k }, (_, a) => Array.from({ length: k }, (_, b) => X.reduce((s, r) => s + r[a] * r[b], 0)));
  const Xty = Array.from({ length: k }, (_, a) => X.reduce((s, r, i) => s + r[a] * y[i], 0));
  const inv = invert(XtX);
  const beta = inv.map(row => row.reduce((s, v, j) => s + v * Xty[j], 0));
  const resid = y.map((v, i) => v - X[i].reduce((s, x, j) => s + x * beta[j], 0));
  return { beta, inv, resid };
}

export function ols(ys, cols, names) {
  const rows = [], y = [];
  ys.forEach((v, i) => { const r = cols.map(c => c[i]); if (isNum(v) && r.every(isNum)) { y.push(v); rows.push(r); } });
  const n = y.length, k = cols.length;
  if (n <= k + 2) return { n, error: 'too few observations' };
  const X = rows.map(r => [1, ...r]);
  const { beta, inv, resid } = fit(y, X);
  const dof = n - k - 1;
  const sse = resid.reduce((s, e) => s + e * e, 0);
  const s2 = sse / dof;
  const my = mean(y);
  const r2 = 1 - sse / y.reduce((s, v) => s + (v - my) ** 2, 0);
  let dw = 0;
  for (let i = 1; i < n; i++) dw += (resid[i] - resid[i - 1]) ** 2;
  const vif = [null];
  for (let j = 0; j < k; j++) {
    if (k === 1) { vif.push(1); break; }
    const xj = rows.map(r => r[j]);
    const others = rows.map(r => [1, ...r.filter((_, q) => q !== j)]);
    const f = fit(xj, others);
    const mj = mean(xj);
    const r2j = 1 - f.resid.reduce((s, e) => s + e * e, 0) / xj.reduce((s, v) => s + (v - mj) ** 2, 0);
    vif.push(r2j < 1 ? 1 / (1 - r2j) : Infinity);
  }
  return {
    n, r2, adj_r2: 1 - (1 - r2) * (n - 1) / dof, durbin_watson: dw / sse,
    coef: ['intercept', ...names].map((name, i) => {
      const se = Math.sqrt(s2 * inv[i][i]), t = beta[i] / se;
      return { name, b: beta[i], se, t, p: tTwoSided(t, dof), vif: vif[i] };
    }),
  };
}
