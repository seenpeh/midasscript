/* The crosshair legend and the trade tooltip — HTML only, no chart access. */

import {fmt, signClass, shortDt, utcMinute} from '../core/format.js';
import {COLORS} from './theme.js';

export const LEGEND_KEYS =
  `<span>EMA fast <b style="color:${COLORS.emaFast}">━</b></span>` +
  `<span>EMA slow <b style="color:${COLORS.emaSlow}">━</b></span>`;

/* `shown` says which price series are drawn ({ohlc, line}): candles get the
   full bar readout, the bare line gets its close. */
export function legendHTML(row, timeframe, shown) {
  const [time, open, high, low, close] = row;
  const color = close >= open ? COLORS.up : COLORS.down;
  const cell = (label, value) => `<span>${label}<b style="color:${color}">${fmt(value)}</b></span>`;
  const out = `<span><b>${utcMinute(time)}</b></span>` +
              `<span class="tf-chip">${timeframe}</span>`;
  // with candles on, C already reads out the close the line draws
  if (shown.ohlc) {
    return out + cell('O', open) + cell('H', high) + cell('L', low) + cell('C', close);
  }
  return out + `<span>Close<b style="color:${COLORS.line}">${fmt(close)}</b></span>`
       + LEGEND_KEYS;
}

const row = (key, value, cls = '') =>
  `<div class="tt-row"><span>${key}</span><b class="${cls}">${value}</b></div>`;

export function tradeTooltipHTML(trade, alsoOnBar = 0) {
  const long = trade.direction === 'long';
  const head = `<div class="tt-head">` +
    `<span class="tag ${long ? 'long' : 'short'}">${long ? 'LONG' : 'SHORT'} #${trade.id}</span>` +
    `<span class="tt-reason">${trade.reason}</span></div>`;
  const body =
    row('Trigger', trade.reason) +
    row('Entry', `${fmt(trade.entry_price)} · ${shortDt(trade.entry_dt)}`) +
    row('Exit', `${fmt(trade.exit_price)} · ${trade.exit_reason}`) +
    row('Position size', fmt(trade.qty, 4)) +
    row('Risk', `${fmt(trade.risk_pct, 2)}%  (RR 1:${fmt(trade.rr, 1)})`) +
    row('PnL', (trade.pnl >= 0 ? '+' : '') + fmt(trade.pnl), signClass(trade.pnl)) +
    row('Equity after', fmt(trade.equity_after));
  const more = alsoOnBar > 0
    ? `<div class="tt-more">+${alsoOnBar} more on this bar</div>` : '';
  return head + body + more;
}
