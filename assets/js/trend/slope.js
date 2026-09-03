/* The slope of the smoothed price line — the exact line the chart draws.

   `smoothing.js` produces one smoothed close per bar (SG, SMA or EMA over the
   chosen window); the drawn line is the polyline through those points. The
   trend measures THAT line's slope, so it can never disagree in sign or shape
   with what is on screen: the slope at each bar is the central difference of
   the smoothed series, one-sided at the two ends, in price per bar.

   (An earlier version read the SG fit's analytic first derivative instead. For
   a symmetric window the two agree, but for a strongly asymmetric one — say
   back 20, fwd 120 — the local parabola can tilt UP at its centre while the
   sequence of plotted centres falls, so the analytic slope took the opposite
   sign to the visible line. The difference of the drawn values has no such gap.)

   LOOK-AHEAD: a window with `fwd > 0` uses bars to the right of each bar, so
   the smoothed line — and this slope with it — repaints. That is fine, because
   the plotted line does exactly the same. For a live signal set fwd = 0. */

import {smoothValues} from './smoothing.js';

/** Candle rows -> slope of the smoothed line at each bar, in price per bar.
    `setting` is a preset level or a custom {kind, back, fwd} window. */
export function smoothSlopes(candles, setting) {
  return differences(smoothValues(candles, setting), new Float64Array(candles.length));
}

/** Central difference of a smoothed series, one-sided at the two ends. */
function differences(values, out) {
  const n = values.length;
  if (n < 2) return out;
  for (let i = 0; i < n; i++) {
    out[i] = i === 0 ? values[1] - values[0]
      : i === n - 1 ? values[n - 1] - values[n - 2]
      : (values[i + 1] - values[i - 1]) / 2;
  }
  return out;
}
