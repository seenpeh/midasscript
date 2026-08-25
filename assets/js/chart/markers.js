/* Arrows, dots and hole flags on the price series, plus the bar->trades index.

   Trades always happen on 5m bars. On a higher timeframe several of them fall
   inside one drawn candle, so they are indexed by the candle that CONTAINS the
   fill and the tooltip lists everything that happened inside that bar. */

import {snapToBar} from './timeframes.js';
import {COLORS} from './theme.js';

/** Map of candle-time -> {entries: [...], exits: [...]}. */
export function buildTradeIndex(view, trades) {
  const index = new Map();
  const add = (time, kind, trade) => {
    const bar = snapToBar(view, time);
    if (bar === null) return;
    if (!index.has(bar)) index.set(bar, {entries: [], exits: []});
    index.get(bar)[kind].push(trade);
  };
  for (const trade of trades) {
    add(trade.entry_time, 'entries', trade);
    add(trade.exit_time, 'exits', trade);
  }
  return index;
}

export function buildMarkers(view, {trades = [], holes = [],
                                    showTrades = true, showHoles = true} = {}) {
  const markers = [];
  if (showTrades) {
    markers.push(...entryMarkers(view, trades), ...exitMarkers(view, trades));
  }
  if (showHoles) markers.push(...holeMarkers(view, holes));
  markers.sort((a, b) => a.time - b.time);
  return markers;
}

/* One arrow per (bar, direction): on 1D a single candle can hold dozens of 5m
   entries, and stacking dozens of arrows on it just hides the price. The count
   says how many; the tooltip lists them. */
function entryMarkers(view, trades) {
  const byBar = new Map();
  for (const trade of trades) {
    const bar = snapToBar(view, trade.entry_time);
    if (bar === null) continue;
    const key = bar + '|' + trade.direction;
    const group = byBar.get(key);
    if (group) group.count++;
    else byBar.set(key, {time: bar, direction: trade.direction, id: trade.id, count: 1});
  }
  return Array.from(byBar.values(), group => {
    const long = group.direction === 'long';
    return {
      time: group.time,
      position: long ? 'belowBar' : 'aboveBar',
      color: long ? COLORS.up : COLORS.down,
      shape: long ? 'arrowUp' : 'arrowDown',
      text: (long ? 'L' : 'S') + (group.count > 1 ? '×' + group.count : '#' + group.id),
    };
  });
}

/* One dot per bar, coloured by the net PnL of everything that closed there. */
function exitMarkers(view, trades) {
  const byBar = new Map();
  for (const trade of trades) {
    const bar = snapToBar(view, trade.exit_time);
    if (bar === null) continue;
    byBar.set(bar, (byBar.get(bar) || 0) + trade.pnl);
  }
  return Array.from(byBar, ([time, pnl]) => ({
    time, position: 'aboveBar', shape: 'circle',
    color: pnl >= 0 ? COLORS.up : COLORS.down,
  }));
}

/* Data holes: flag the last bar before each one, on every timeframe. */
function holeMarkers(view, holes) {
  const markers = [];
  for (const hole of holes) {
    const bar = snapToBar(view, hole.start);
    if (bar === null) continue;
    const days = hole.hours / 24;
    markers.push({
      time: bar, position: 'aboveBar', color: COLORS.hole, shape: 'square',
      text: '⛔ ' + (days >= 1 ? days.toFixed(1) + 'd' : hole.hours.toFixed(1) + 'h')
            + ' no data',
    });
  }
  return markers;
}
