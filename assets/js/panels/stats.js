/* The Statistics tab. */

import {$} from '../core/dom.js';
import {fmt, fmtInt, signed, signClass} from '../core/format.js';
import {store} from '../data/store.js';

/* The three numbers that decide whether the run was any good. Everything else
   is supporting detail and reads as a quiet row, not as another equal box. */
const LEAD = [
  ['Net profit', s => fmt(s.net_profit), s => signClass(s.net_profit),
    s => `${signed(s.return_pct)}% return`],
  ['Max drawdown', s => fmt(s.max_drawdown_pct) + '%', () => 'neg',
    s => fmt(s.max_drawdown) + ' peak to trough'],
  ['Profit factor', s => s.profit_factor == null ? '—' : fmt(s.profit_factor, 2),
    s => s.profit_factor >= 1 ? 'pos' : 'neg',
    s => `${fmtInt(s.total_trades)} trades · ${fmt(s.win_rate)}% win`],
];

const CAPITAL = [
  ['Initial capital', s => fmt(s.initial_capital)],
  ['Final equity', s => fmt(s.final_equity), s => signClass(s.final_equity - s.initial_capital)],
  ['CAGR', s => signed(s.cagr_pct) + '%', s => signClass(s.cagr_pct)],
  ['Expectancy / trade', s => fmt(s.expectancy), s => signClass(s.expectancy)],
];

const PROFILE = [
  ['Wins / losses', s => `${fmtInt(s.wins)} / ${fmtInt(s.losses)}`],
  ['Avg win / loss', s => `${fmt(s.avg_win)} / ${fmt(s.avg_loss)}`],
  ['Largest win', s => fmt(s.largest_win), () => 'pos'],
  ['Largest loss', s => fmt(s.largest_loss), () => 'neg'],
  ['Max consec W / L', s => `${s.max_consec_wins} / ${s.max_consec_losses}`],
  ['Avg bars held', s => fmt(s.avg_bars_held, 1)],
  ['Long (win%)', s => `${fmtInt(s.long_trades)} (${fmt(s.long_win_rate)}%)`],
  ['Short (win%)', s => `${fmtInt(s.short_trades)} (${fmt(s.short_win_rate)}%)`],
];

const leadCell = (stats, [label, value, cls, sub]) =>
  `<div><div class="k">${label}</div>` +
  `<div class="v ${cls ? cls(stats) : ''}">${value(stats)}</div>` +
  `<div class="sub">${sub(stats)}</div></div>`;

/** A definition list of label/value pairs, rendered as the same quiet table
    the breakdowns use so the whole tab shares one row rhythm. */
const rows = (stats, spec) => table(null, spec.map(([label, value, cls]) =>
  [label, cell(value(stats), 'kv ' + (cls ? cls(stats) : ''))]));

export function renderStats() {
  const stats = store.stats, meta = store.meta;

  const byTrigger = table(
    ['Trigger', 'Trades', 'Win%', 'Net PnL'],
    Object.entries(stats.by_trigger).map(([name, group]) => [
      name, fmtInt(group.trades), fmt(group.win_rate) + '%',
      cell(fmt(group.net_pnl), 'kv ' + signClass(group.net_pnl))]));

  const byExit = table(
    ['Reason', 'Count', 'Net PnL'],
    Object.entries(stats.by_exit).map(([name, group]) => [
      name, fmtInt(group.count),
      cell(fmt(group.net_pnl), 'kv ' + signClass(group.net_pnl))]));

  const runInfo = table(null, [
    ['Data range', cell(`${meta.data_start} → ${meta.data_end}`, 'kv')],
    ['Bars', cell(fmtInt(meta.bars), 'kv')],
    ['Same-bar fill', cell(meta.same_bar_fill, 'kv')],
    ['Ruined', cell(meta.ruined ? 'yes · ' + meta.ruin_date : 'no', 'kv')],
    ['Risk / trade', cell(meta.params.t1_risk + '%', 'kv')],
    ['Pyramiding', cell(meta.params.pyramiding, 'kv')],
    ['Spread', cell(meta.spread != null ? '$' + fmt(meta.spread, 2) : '—', 'kv')],
    ['EMA fast / slow', cell(`${meta.params.ema_fast_len} / ${meta.params.ema_slow_len}`, 'kv')],
  ]);

  $('#statsBody').innerHTML =
    `<div class="stat-lead">${LEAD.map(spec => leadCell(stats, spec)).join('')}</div>` +
    '<h3>Capital</h3>' + rows(stats, CAPITAL) +
    '<h3>Trade profile</h3>' + rows(stats, PROFILE) +
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
