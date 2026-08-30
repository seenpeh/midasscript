/* The instantaneous slope of the smoothed price line.

   `smoothing.js` fits a local PARABOLA to the closes around each bar and takes
   its centre value — that is the curve you see. This module takes the same
   fit's FIRST DERIVATIVE at that same point: the exact instantaneous slope of
   the drawn curve, in price per bar. No second smoothing pass, no extra window
   to tune, and nothing that can drift away from the line on screen.

   The window is whatever the line uses — a preset level, or a custom
   {back, fwd}. For a symmetric window the parabola's linear coefficient
   separates out cleanly into w[i] = i / Σi²; the asymmetric case comes from
   the same normal equations, one row lower.

   LOOK-AHEAD: a window with `fwd > 0` uses bars to the right of each bar, so
   the trend it feeds repaints — which is fine, because the plotted line does
   exactly the same and the two agree on screen. For a live signal set fwd = 0:
   the fit is then trailing-only and nothing here changes. */

import {sgCoefWeights, smoothWindow} from './smoothing.js';

/** Derivative weights for the window -back..fwd, in price per bar. */
export function sgSlopeWeights(back, fwd) {
  return sgCoefWeights(back, fwd, 1);
}

/** Candle rows -> slope of the smoothed line at each bar, in price per bar.
    `setting` is a preset level or a custom {back, fwd} window. A window too
    small to fit a parabola falls back to the plain bar-to-bar change. */
export function smoothSlopes(candles, setting) {
  const n = candles.length;
  const {back, fwd} = smoothWindow(setting);
  const out = new Float64Array(n);
  if (n < 2) return out;
  for (let i = 0; i < n; i++) {
    const b = Math.min(back, i);                    // largest window that fits
    const f = Math.min(fwd, n - 1 - i);
    if (b + f < 2) {
      out[i] = i > 0 ? candles[i][4] - candles[i - 1][4] : 0;
      continue;
    }
    const weights = sgSlopeWeights(b, f);
    let slope = 0;
    for (let k = -b; k <= f; k++) slope += weights[k + b] * candles[i + k][4];
    out[i] = slope;
  }
  return out;
}
