/* The daily homework bar: how many candles were labelled TODAY, per timeframe.

   "Today" is the trader's own local day — the labels carry a server timestamp
   and the counting happens here, so there is no timezone setting to get wrong.

   A candle counts once it is inside a stored rectangle. Gaps between
   rectangles are allowed and count for nothing: unlabelled candles are simply
   not training data. */

export function startOfToday(now = new Date()) {
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  return Math.floor(midnight.getTime() / 1000);
}

/** Candles labelled today on `tf`, and the all-time total. */
export function tally(labels, tf, since = startOfToday()) {
  let today = 0, total = 0;
  for (const label of labels) {
    if (label.tf !== tf) continue;
    total += label.bars;
    if (label.created_at >= since) today += label.bars;
  }
  return {today, total};
}

/** Draw the bar. `pending` is the candle count of the rectangle being drawn. */
export function renderHomework(host, {labels, quota, timeframe, pending}) {
  const since = startOfToday();
  const pills = Object.keys(quota).map(tf => {
    const {today, total} = tally(labels, tf, since);
    const goal = quota[tf];
    const classes = ['hw'];
    if (today >= goal) classes.push('hw--done');
    if (tf === timeframe) classes.push('hw--now');
    return `<span class="${classes.join(' ')}" title="${total.toLocaleString()} candles labelled on ${tf} all time">
      <b>${tf}</b> <span class="num">${today.toLocaleString()}/${goal.toLocaleString()}</span>
      ${today >= goal ? '✓' : ''}</span>`;
  }).join('');
  const note = pending
    ? `<span class="hw-note">selecting <b class="num">${pending.toLocaleString()}</b> candle${pending === 1 ? '' : 's'} — click the last candle, Esc cancels</span>`
    : '<span class="hw-note">pick a trend, then click the first and last candle · click a rectangle and press Delete to remove it</span>';
  host.innerHTML = `<div class="hw-row">${pills}</div>${note}`;
}
