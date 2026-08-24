/* Aggregating the 5-minute file into the timeframe you are looking at.

   The file on disk is always 5-minute bars — that is the resolution the
   strategy trades on and the resolution every trade in results.json refers to.
   The higher timeframes are built HERE, in the browser, from those same bars,
   so switching timeframe changes only what you see: never a trade, a fill or a
   statistic.

   Two rules keep the aggregation honest, and they mirror the Python side in
   midas/data/timeframes.py exactly:
     - buckets are aligned to the epoch (a 4h bar starts at 00/04/08/... UTC,
       not at whatever time the window happens to begin), and
     - a bucket never spans a DATA HOLE. The bar after a hole opens a fresh
       candle, so a 1D candle cannot quietly weld 2025-09-12 onto 2025-10-15 and
       report the 32 days between them as one $537 daily range.

   Everything in this module is a pure function of its arguments. */

export const TF_SECONDS = {'5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1D': 86400};
export const TF_ORDER = ['5m', '15m', '1h', '4h', '1D'];
export const BASE_SECONDS = 300;

/** Bucket id per 5m bar: the epoch its higher-timeframe candle opens at.
    `holeIdx` holds indices i where a hole sits between bar i and i+1 — the run
    starting at i+1 gets its own leading (partial) bucket. */
export function bucketIds(candles, seconds, holeIdx) {
  const n = candles.length;
  const buckets = new Array(n);
  for (let i = 0; i < n; i++) buckets[i] = Math.floor(candles[i][0] / seconds) * seconds;
  for (const hole of holeIdx) {
    const first = hole + 1;
    if (first <= 0 || first >= n) continue;
    const id = buckets[first];
    let end = first;
    while (end < n && buckets[end] === id) end++;
    for (let k = first; k < end; k++) buckets[k] = candles[first][0];
  }
  return buckets;
}

/** Aggregate to `tf`: OHLC = first open / max high / min low / last close,
    volume sums, and indicator lines are sampled at each bucket's CLOSE — the
    value that candle actually closed on. Returns a view: {tf, sec, candles,
    emaFast, emaSlow}. */
export function buildView(tf, {candles = [], emaFast = [], emaSlow = [], holes = []} = {}) {
  const seconds = TF_SECONDS[tf] || BASE_SECONDS;
  if (seconds <= BASE_SECONDS || candles.length < 2) {
    return {tf, sec: BASE_SECONDS, candles, emaFast, emaSlow};
  }
  const holeIdx = holes.map(h => h.i).filter(i => i >= 0 && i < candles.length - 1);
  const buckets = bucketIds(candles, seconds, holeIdx);

  const starts = [];
  for (let i = 0; i < candles.length; i++) {
    if (i === 0 || buckets[i] !== buckets[i - 1]) starts.push(i);
  }

  const bars = new Array(starts.length);
  const fast = emaFast.length ? new Array(starts.length) : [];
  const slow = emaSlow.length ? new Array(starts.length) : [];
  for (let k = 0; k < starts.length; k++) {
    const from = starts[k];
    const to = (k + 1 < starts.length ? starts[k + 1] : candles.length);
    let high = candles[from][2], low = candles[from][3], volume = 0;
    for (let i = from; i < to; i++) {
      if (candles[i][2] > high) high = candles[i][2];
      if (candles[i][3] < low) low = candles[i][3];
      volume += candles[i][5];
    }
    const time = buckets[from];
    bars[k] = [time, candles[from][1], high, low, candles[to - 1][4], volume];
    if (emaFast.length) fast[k] = [time, emaFast[to - 1][1]];
    if (emaSlow.length) slow[k] = [time, emaSlow[to - 1][1]];
  }
  return {tf, sec: seconds, candles: bars, emaFast: fast, emaSlow: slow};
}

/** Index of the drawn bar that CONTAINS time t — bars are contiguous and in
    order, so it is the last one opening at or before t. -1 if t is before them. */
export function barIndexAt(view, t) {
  const bars = view.candles, n = bars.length;
  if (!n || t < bars[0][0]) return -1;
  let low = 0, high = n - 1;
  while (low < high) {
    const mid = (low + high + 1) >> 1;
    if (bars[mid][0] <= t) low = mid; else high = mid - 1;
  }
  return low;
}

/** Bar-open time of the drawn candle containing t, or null if t is outside. */
export function snapToBar(view, t) {
  const index = barIndexAt(view, t);
  if (index < 0) return null;
  const last = view.candles[view.candles.length - 1][0];
  if (t > last) return null;
  return view.candles[index][0];
}

/** The candle row nearest a (possibly interpolated) crosshair time, or null if
    the crosshair is more than one bar away from any of them. */
export function nearestBar(view, t) {
  const bars = view.candles, n = bars.length;
  if (!n) return null;
  let low = 0, high = n - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (bars[mid][0] < t) low = mid + 1; else high = mid;
  }
  let best = low;
  if (low > 0 && Math.abs(bars[low - 1][0] - t) <= Math.abs(bars[low][0] - t)) best = low - 1;
  const bar = bars[best];
  if (Math.abs(bar[0] - t) > view.sec) return null;
  return {row: bar, time: bar[0]};
}
