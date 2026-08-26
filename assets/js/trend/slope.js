/* The instantaneous slope of the smoothed price line.

   `smoothing.js` fits a local PARABOLA to the closes around each bar and takes
   its centre value — that is the curve you see. This module takes the same
   fit's FIRST DERIVATIVE at that same point: the exact instantaneous slope of
   the drawn curve, in price per bar. No second smoothing pass, no extra window
   to tune, and nothing that can drift away from the line on screen.

   For a symmetric window the parabola's linear coefficient separates out
   cleanly, leaving weights w[i] = i / Σi² — so the derivative is a single
   weighted sum, exactly like the value itself.

   LOOK-AHEAD: the window is symmetric, so bar i uses m bars to its right. The
   plotted line already does this, so the slope agrees with what you see. A
   live signal needs one-sided weights instead: replace `sgSlopeWeights` with a
   trailing-window fit and nothing else here changes. */

import {MAX_LEVEL} from './smoothing.js';

const weightCache = new Map();

/** Derivative weights for half-width m: w[i] = i / Σi², summing i²=m(m+1)(2m+1)/3. */
export function sgSlopeWeights(m) {
  if (m <= 0) return [0];
  if (weightCache.has(m)) return weightCache.get(m);
  const sumSquares = m * (m + 1) * (2 * m + 1) / 3;
  const weights = new Array(2 * m + 1);
  for (let i = -m; i <= m; i++) weights[i + m] = i / sumSquares;
  weightCache.set(m, weights);
  return weights;
}

/** Candle rows -> slope of the level-`level` smoothed line at each bar,
    in price per bar. Level 0 has no window, so it falls back to the plain
    bar-to-bar change of the raw closes. */
export function smoothSlopes(candles, level) {
  const n = candles.length;
  const clamped = Math.max(0, Math.min(MAX_LEVEL, level | 0));
  const out = new Float64Array(n);
  if (n < 2) return out;
  const halfWidth = clamped * 2;
  for (let i = 0; i < n; i++) {
    const m = Math.min(halfWidth, i, n - 1 - i);    // largest window that fits
    if (m <= 0) {
      out[i] = i > 0 ? candles[i][4] - candles[i - 1][4] : 0;
      continue;
    }
    const weights = sgSlopeWeights(m);
    let slope = 0;
    for (let k = -m; k <= m; k++) slope += weights[k + m] * candles[i + k][4];
    out[i] = slope;
  }
  return out;
}
