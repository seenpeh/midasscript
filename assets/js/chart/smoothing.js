/* The smooth price line: 11 levels (0..10) of Savitzky–Golay filtering.

   A plain moving average flattens peaks and lags turns — it blurs structure as
   much as noise. Savitzky–Golay fits a local PARABOLA (least squares) in each
   window and takes its centre, so it strips high-frequency noise while keeping
   the real swings, peaks and troughs. Level 0 is the raw close; each level
   widens the window by 4 bars (level 10 is roughly a 41-bar fit). Points keep
   their original bar timestamps so markers and price lines anchor exactly. */

export const MAX_LEVEL = 10;

const weightCache = new Map();

/** Quadratic SG smoothing weights for half-width m (they sum to 1). */
export function sgWeights(m) {
  if (m <= 0) return [1];
  if (weightCache.has(m)) return weightCache.get(m);
  const denominator = (2 * m + 3) * (2 * m + 1) * (2 * m - 1);
  const weights = new Array(2 * m + 1);
  for (let i = -m; i <= m; i++) {
    weights[i + m] = 3 * (3 * m * m + 3 * m - 1 - 5 * i * i) / denominator;
  }
  weightCache.set(m, weights);
  return weights;
}

/** Candle rows -> [{time, value}] closes, smoothed at `level`. */
export function smoothCloses(candles, level) {
  const n = candles.length;
  const clamped = Math.max(0, Math.min(MAX_LEVEL, level | 0));
  if (clamped <= 0 || n < 5) return candles.map(r => ({time: r[0], value: r[4]}));
  const halfWidth = clamped * 2;
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const m = Math.min(halfWidth, i, n - 1 - i);   // largest window that fits
    if (m <= 0) { out[i] = {time: candles[i][0], value: candles[i][4]}; continue; }
    const weights = sgWeights(m);
    let value = 0;
    for (let k = -m; k <= m; k++) value += weights[k + m] * candles[i + k][4];
    out[i] = {time: candles[i][0], value};
  }
  return out;
}
