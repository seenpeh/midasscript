/* The title bar: the run's headline numbers and the line under the title. */

import {$} from '../core/dom.js';
import {fmt, fmtInt, signed, signClass} from '../core/format.js';
import {store} from '../data/store.js';

const ALERT_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M12 4 2.5 20h19z"/><path d="M12 10v4.5M12 17.4v.1"/></svg>';

const CHIPS = [
  ['Net profit', s => fmt(s.net_profit), s => signClass(s.net_profit)],
  ['Return', s => signed(s.return_pct) + '%', s => signClass(s.return_pct)],
  ['Win rate', s => fmt(s.win_rate) + '%', () => ''],
  ['Profit factor', s => s.profit_factor == null ? '—' : fmt(s.profit_factor, 2),
    s => s.profit_factor >= 1 ? 'pos' : 'neg'],
  ['Max DD', s => fmt(s.max_drawdown_pct) + '%', () => 'neg'],
  ['Trades', s => fmtInt(s.total_trades), () => ''],
];

export function renderHeader(view) {
  const stats = store.stats, meta = store.meta;
  renderMeta(view);
  $('#ruinBadge').innerHTML = meta.ruined ? `<span class="badge-ruin">${ALERT_ICON}` +
    `Account ruined ${meta.ruin_date}</span>` : '';
  $('#chips').innerHTML = CHIPS.map(([label, value, cls]) =>
    `<div class="chip"><span class="k">${label}</span>` +
    `<span class="v ${cls(stats)}">${value(stats)}</span></div>`).join('');
}

/** The small grey line under the title: window, drawn timeframe, bar count. */
export function renderMeta(view) {
  const meta = store.meta;
  const bars = (view && view.candles.length) || meta.bars;
  const holes = store.holes;
  const gaps = holes.length
    ? ` · ${holes.length} data hole${holes.length > 1 ? 's' : ''}` : '';
  const timeframe = view ? view.tf : '5m';
  $('#dateRange').textContent =
    `${meta.data_start} → ${meta.data_end} · ${timeframe} · ${fmtInt(bars)} bars` +
    (timeframe === '5m' ? '' : ' (from 5m)') + gaps;
}
