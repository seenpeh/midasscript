/* The smooth price line: Savitzky–Golay filtering, either at one of 11 preset
   levels (0..10) or over a custom window the user types in.

   A plain moving average flattens peaks and lags turns — it blurs structure as
   much as noise. Savitzky–Golay fits a local PARABOLA (least squares) in each
   window and takes its centre, so it strips high-frequency noise while keeping
   the real swings, peaks and troughs. Level 0 is the raw close; each level
   widens the window by 4 bars (level 10 is roughly a 41-bar fit). Points keep
   their original bar timestamps so markers and price lines anchor exactly.

   The window need not be symmetric: {back, fwd} fits the parabola over `back`
   bars behind and `fwd` bars ahead and still reads it at the current bar, so
   `{back: 20, fwd: 0}` is a causal (non-repainting) filter and `{back: 5,
   fwd: 5}` is the classic 11-bar centred one. */

export const MAX_LEVEL = 10;
export const MAX_BARS = 500;      // per side; a wider fit is a different tool

const weightCache = new Map();

const clampBars = value => Math.max(0, Math.min(MAX_BARS, Math.round(+value) || 0));

/** Normalise a smoothing setting into a {back, fwd} bar window. A number (or
    anything else) is read as a preset level; `{back, fwd}` passes through. */
export function smoothWindow(setting) {
  if (setting && typeof setting === 'object') {
    return {back: clampBars(setting.back), fwd: clampBars(setting.fwd)};
  }
  const level = Math.max(0, Math.min(MAX_LEVEL, setting | 0));
  return {back: level * 2, fwd: level * 2};
}

/** Least-squares quadratic fit over x = -back..fwd, read at x = 0: the weights
    that produce coefficient `order` of the parabola (0 = value, 1 = slope per
    bar, 2 = curvature/2). Solving the normal equations through the inverse
    moment matrix makes an asymmetric window no special case. */
export function sgCoefWeights(back, fwd, order) {
  const key = back + ':' + fwd + ':' + order;
  const cached = weightCache.get(key);
  if (cached) return cached;

  const count = back + fwd + 1;
  const weights = new Array(count).fill(0);
  if (count < 3) {                        // too few points to pin a parabola
    if (order === 0) weights[back] = 1;   // ... so the value is the bar itself
    weightCache.set(key, weights);
    return weights;
  }
  // power sums S0..S4 of the offsets
  const s = [0, 0, 0, 0, 0];
  for (let x = -back; x <= fwd; x++) {
    let power = 1;
    for (let k = 0; k < 5; k++) { s[k] += power; power *= x; }
  }
  // M = [[S0,S1,S2],[S1,S2,S3],[S2,S3,S4]] (symmetric); rows of its adjugate
  const adj = [
    [s[2] * s[4] - s[3] * s[3], s[2] * s[3] - s[1] * s[4], s[1] * s[3] - s[2] * s[2]],
    [s[2] * s[3] - s[1] * s[4], s[0] * s[4] - s[2] * s[2], s[1] * s[2] - s[0] * s[3]],
    [s[1] * s[3] - s[2] * s[2], s[1] * s[2] - s[0] * s[3], s[0] * s[2] - s[1] * s[1]],
  ];
  const det = s[0] * adj[0][0] + s[1] * adj[0][1] + s[2] * adj[0][2];
  if (!det) {                             // degenerate: keep the bar untouched
    if (order === 0) weights[back] = 1;
  } else {
    const [a, b, c] = adj[order];
    for (let x = -back; x <= fwd; x++) weights[x + back] = (a + b * x + c * x * x) / det;
  }
  weightCache.set(key, weights);
  return weights;
}

/** Quadratic SG smoothing weights over x = -back..fwd, read at x = 0 (they sum
    to 1). */
export function sgWeights(back, fwd) {
  return sgCoefWeights(back, fwd, 0);
}

/** Candle rows -> [{time, value}] closes, smoothed with `setting` (a preset
    level, or a custom `{back, fwd}` window). Near the ends of the data each
    side shrinks to what actually fits. */
export function smoothCloses(candles, setting) {
  const n = candles.length;
  const {back, fwd} = smoothWindow(setting);
  if (back + fwd === 0 || n < 5) return candles.map(r => ({time: r[0], value: r[4]}));
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const b = Math.min(back, i);                 // largest window that fits
    const f = Math.min(fwd, n - 1 - i);
    if (b + f < 2) { out[i] = {time: candles[i][0], value: candles[i][4]}; continue; }
    const weights = sgWeights(b, f);
    let value = 0;
    for (let k = -b; k <= f; k++) value += weights[k + b] * candles[i + k][4];
    out[i] = {time: candles[i][0], value};
  }
  return out;
}
