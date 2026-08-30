/* The fuzzy trend number: one value per bar in 0..1.

     0.0  fully down     0.5  sideways     1.0  fully up

   THE TARGET (what this file defines, and what later tuning is measured
   against): the number is the ANGLE of the smoothed price line, mapped from
   -90°..+90° onto 0..1 linearly —

       f = 0.5 + angle / 180°

   An angle only exists once price and time share a unit: a $2-per-bar slope is
   steep in a quiet market and flat in a wild one, and reading the angle off the
   screen would make it change every time you zoom. So the slope is divided by
   the bar's own ATR before the angle is taken:

       angle = atan(gain · slope_per_bar / ATR)

   That makes the number self-scaling — comparable between 5m and 1h, and
   between a calm month and a violent one — and leaves `gain` as the single
   knob that says how many ATR-per-bar counts as "fully trending". `gain` and
   the smoothing window are what gets fine-tuned. */

import {smoothSlopes} from './slope.js';

export const TREND_DEFAULTS = {
  smooth: 7,     // window of the line whose slope is measured: a preset level
                 // (0..10) or a custom {back, fwd} bar count, exactly as the
                 // price line takes it
  gain: 5,       // slope/ATR multiplier before atan — the sensitivity knob
  atrLen: 14,    // ATR window, in bars of the timeframe being measured
};

export const NEUTRAL = 0.5;

/** Causal ATR: rolling mean of true range over `len` bars (NaN while warming up). */
export function atr(candles, len) {
  const n = candles.length;
  const out = new Float64Array(n).fill(NaN);
  if (!n) return out;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const [, , high, low] = candles[i];
    const previousClose = i > 0 ? candles[i - 1][4] : null;
    const trueRange = previousClose == null ? high - low
      : Math.max(high - low, Math.abs(high - previousClose), Math.abs(low - previousClose));
    sum += trueRange;
    if (i >= len) sum -= lastTrueRange(candles, i - len);
    if (i >= len - 1) out[i] = sum / len;
  }
  return out;
}

function lastTrueRange(candles, i) {
  const [, , high, low] = candles[i];
  if (i === 0) return high - low;
  const previousClose = candles[i - 1][4];
  return Math.max(high - low, Math.abs(high - previousClose), Math.abs(low - previousClose));
}

/** One slope + one ATR -> the fuzzy number. Flat or unmeasurable reads 0.5. */
export function fuzzyFromSlope(slope, atrValue, gain) {
  if (!isFinite(slope) || !isFinite(atrValue) || atrValue <= 0) return NEUTRAL;
  const angle = Math.atan(gain * slope / atrValue);     // -π/2 .. +π/2
  return NEUTRAL + angle / Math.PI;                     // 0 .. 1
}

/** Candle rows -> [{time, value}] fuzzy trend, computed on those bars' own
    timeframe. Feed it 5m rows for the 5m reading, 1h rows for the 1h one. */
export function trendSeries(candles, options = {}) {
  const {smooth, gain, atrLen} = {...TREND_DEFAULTS, ...options};
  const slopes = smoothSlopes(candles, smooth);
  const ranges = atr(candles, atrLen);
  return candles.map((candle, i) => ({
    time: candle[0], value: fuzzyFromSlope(slopes[i], ranges[i], gain),
  }));
}
