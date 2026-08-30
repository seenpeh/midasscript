/* The smooth price line: one of three filters — Savitzky–Golay, SMA or EMA —
   over a window that is either a preset level (0..10) or a custom {back, fwd}
   the user types in.

   Every filter here is the same shape: a fixed set of weights over the bars
   from `back` behind to `fwd` ahead of each bar, summing to 1. Only the shape
   of the weights differs:

     sg   least-squares PARABOLA through the window, read at the centre. Strips
          high-frequency noise while keeping peaks, troughs and the real swings
          — an average of any kind flattens exactly those.
     sma  flat weights: the plain mean of the window.
     ema  exponential decay away from the current bar, span = that side's
          length. With fwd = 0 this is the familiar EMA, truncated at `back`
          bars instead of running forever.

   A preset level widens the window by 2 bars per side per level (level 10 is
   roughly a 41-bar window); level 0 is the raw close. Points keep their
   original bar timestamps so markers and price lines anchor exactly.

   The window need not be symmetric: `{back: 20, fwd: 0}` is causal (nothing to
   the right, so it never repaints) while `{back: 5, fwd: 5}` is the classic
   centred one that does. */

export const MAX_LEVEL = 10;
export const MAX_BARS = 500;      // per side; a wider fit is a different tool
export const FILTERS = ['sg', 'sma', 'ema'];
export const DEFAULT_FILTER = 'sg';

const weightCache = new Map();

const clampBars = value => Math.max(0, Math.min(MAX_BARS, Math.round(+value) || 0));

/** Normalise a smoothing setting into {kind, back, fwd}. A number (or anything
    else) is read as a preset level of the default filter; an object carries a
    custom window and, optionally, which filter to run over it. */
export function smoothWindow(setting) {
  if (setting && typeof setting === 'object') {
    const kind = FILTERS.includes(setting.kind) ? setting.kind : DEFAULT_FILTER;
    return {kind, back: clampBars(setting.back), fwd: clampBars(setting.fwd)};
  }
  const level = Math.max(0, Math.min(MAX_LEVEL, setting | 0));
  return {kind: DEFAULT_FILTER, back: level * 2, fwd: level * 2};
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

/** Flat weights: the plain mean of the window. */
function smaWeights(back, fwd) {
  return new Array(back + fwd + 1).fill(1 / (back + fwd + 1));
}

/** Exponential weights, decaying away from the current bar. Each side uses the
    standard span factor a = 2/(N+1) for its own length, so `{back: N, fwd: 0}`
    is an ordinary N-span EMA cut off at N bars. */
function emaWeights(back, fwd) {
  const decay = side => (side > 0 ? 1 - 2 / (side + 1) : 0);
  const backDecay = decay(back), fwdDecay = decay(fwd);
  const weights = new Array(back + fwd + 1);
  let total = 0;
  for (let x = -back; x <= fwd; x++) {
    const weight = x === 0 ? 1
      : Math.pow(x < 0 ? backDecay : fwdDecay, Math.abs(x));
    weights[x + back] = weight;
    total += weight;
  }
  for (let i = 0; i < weights.length; i++) weights[i] /= total;
  return weights;
}

/** The weights of filter `kind` over the window -back..fwd (they sum to 1). */
export function filterWeights(kind, back, fwd) {
  const key = kind + ':' + back + ':' + fwd;
  const cached = weightCache.get(key);
  if (cached) return cached;
  const weights = kind === 'sma' ? smaWeights(back, fwd)
    : kind === 'ema' ? emaWeights(back, fwd)
    : sgWeights(back, fwd);
  weightCache.set(key, weights);
  return weights;
}

/** Candle rows -> smoothed closes as a Float64Array, one per bar. Near the ends
    of the data each side of the window shrinks to what actually fits. */
export function smoothValues(candles, setting) {
  const n = candles.length;
  const {kind, back, fwd} = smoothWindow(setting);
  const out = new Float64Array(n);
  const raw = i => candles[i][4];
  if (back + fwd === 0 || n < 5) {
    for (let i = 0; i < n; i++) out[i] = raw(i);
    return out;
  }
  for (let i = 0; i < n; i++) {
    const b = Math.min(back, i);                 // largest window that fits
    const f = Math.min(fwd, n - 1 - i);
    if (b + f < 1 || (kind === 'sg' && b + f < 2)) { out[i] = raw(i); continue; }
    const weights = filterWeights(kind, b, f);
    let value = 0;
    for (let k = -b; k <= f; k++) value += weights[k + b] * raw(i + k);
    out[i] = value;
  }
  return out;
}

/** Candle rows -> [{time, value}] smoothed closes, ready for the chart. */
export function smoothCloses(candles, setting) {
  const values = smoothValues(candles, setting);
  return candles.map((row, i) => ({time: row[0], value: values[i]}));
}
