/* The Statistics tab. */

import {$} from '../core/dom.js';
import {fmt, fmtInt, signed, signClass} from '../core/format.js';
import {store} from '../data/store.js';

const CELLS = [
  ['Initial capital', s => fmt(s.initial_capital)],
  ['Final equity', s => fmt(s.final_equity), s => signClass(s.final_equity - s.initial_capital)],
  ['Net profit', s => fmt(s.net_profit), s => signClass(s.net_profit)],
  ['Return', s => signed(s.return_pct) + '%', s => signClass(s.return_pct)],
  ['CAGR', s => signed(s.cagr_pct) + '%', s => signClass(s.cagr_pct)],
  ['Profit factor', s => s.profit_factor == null ? '—' : fmt(s.profit_factor, 3),
    s => s.profit_factor >= 1 ? 'pos' : 'neg'],
  ['Total trades', s => fmtInt(s.total_trades)],
  ['Win rate', s => fmt(s.win_rate) + '%'],
  ['Wins / Losses', s => `${fmtInt(s.wins)} / ${fmtInt(s.losses)}`],
  ['Avg win / loss', s => `${fmt(s.avg_win)} / ${fmt(s.avg_loss)}`],
  ['Expectancy / trade', s => fmt(s.expectancy), s => signClass(s.expectancy)],
  ['Largest win', s => fmt(s.largest_win), () => 'pos'],
  ['Largest loss', s => fmt(s.largest_loss), () => 'neg'],
  ['Max drawdown', s => `${fmt(s.max_drawdown)} (${fmt(s.max_drawdown_pct)}%)`, () => 'neg'],
  ['Max consec W / L', s => `${s.max_consec_wins} / ${s.max_consec_losses}`],
  ['Avg bars held', s => fmt(s.avg_bars_held, 1)],
  ['Long (win%)', s => `${fmtInt(s.long_trades)} (${fmt(s.long_win_rate)}%)`],
  ['Short (win%)', s => `${fmtInt(s.short_trades)} (${fmt(s.short_win_rate)}%)`],
];

const statCell = (label, value, cls = '') =>
  `<div class="stat"><div class="k">${label}</div><div class="v ${cls}">${value}</div></div>`;

export function renderStats() {
  const stats = store.stats, meta = store.meta;
  const grid = CELLS.map(([label, value, cls]) =>
    statCell(label, value(stats), cls ? cls(stats) : '')).join('');

  const byTrigger = table(
    ['Trigger', 'Trades', 'Win%', 'Net PnL'],
    Object.entries(stats.by_trigger).map(([name, group]) => [
      name, fmtInt(group.trades), fmt(group.win_rate) + '%',
      cell(fmt(group.net_pnl), signClass(group.net_pnl))]));

  const byExit = table(
    ['Reason', 'Count', 'Net PnL'],
    Object.entries(stats.by_exit).map(([name, group]) => [
      name, fmtInt(group.count),
      cell(fmt(group.net_pnl), signClass(group.net_pnl))]));

  const runInfo = table(null, [
    ['Data range', `${meta.data_start} → ${meta.data_end}`],
    ['Bars', fmtInt(meta.bars)],
    ['Same-bar fill', meta.same_bar_fill],
    ['Ruined', meta.ruined ? 'yes · ' + meta.ruin_date : 'no'],
    ['Risk / trade', meta.params.t1_risk + '%'],
    ['Pyramiding', meta.params.pyramiding],
    ['Spread', meta.spread != null ? '$' + fmt(meta.spread, 2) : '—'],
    ['EMA fast / slow', `${meta.params.ema_fast_len} / ${meta.params.ema_slow_len}`],
  ]);

  $('#statsBody').innerHTML =
    `<div class="stat-grid">${grid}</div>` +
    '<h3>By trigger</h3>' + byTrigger +
    '<h3>By exit reason</h3>' + byExit +
    '<h3>Run info</h3>' + runInfo;
}

const cell = (value, cls) => `<td class="${cls}">${value}</td>`;

function table(headers, rows) {
  const head = headers ? `<tr>${headers.map(h => `<td>${h}</td>`).join('')}</tr>` : '';
  const body = rows.map(cells =>
    '<tr>' + cells.map(c => String(c).startsWith('<td') ? c : `<td>${c}</td>`).join('') + '</tr>'
  ).join('');
  return `<table class="brk">${head}${body}</table>`;
}
