/* The monthly profit & drawdown modal: a calendar heat map of the equity curve. */

import {$} from '../core/dom.js';
import {fmt} from '../core/format.js';
import {store} from '../data/store.js';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const RETURN_SCALE = 20;    // % return that saturates the green/red shading
const DD_SCALE = 30;        // % drawdown that saturates the red shading

/** month key -> {year, month, start, pnl, peak, equity, maxDrawdown, trades} */
export function monthlyBuckets(trades, initialCapital) {
  const ordered = [...trades].sort((a, b) => a.exit_time - b.exit_time);
  const months = new Map();
  let previousEquity = initialCapital;
  for (const trade of ordered) {
    const date = new Date(trade.exit_time * 1000);
    const key = date.getUTCFullYear() + '-' + date.getUTCMonth();
    if (!months.has(key)) {
      months.set(key, {year: date.getUTCFullYear(), month: date.getUTCMonth(),
        start: previousEquity, pnl: 0, peak: previousEquity,
        equity: previousEquity, maxDrawdown: 0, trades: 0});
    }
    const bucket = months.get(key);
    bucket.pnl += trade.pnl;
    bucket.trades++;
    bucket.equity = trade.equity_after;
    bucket.peak = Math.max(bucket.peak, bucket.equity);
    if (bucket.peak > 0) {
      bucket.maxDrawdown = Math.max(bucket.maxDrawdown,
        (bucket.peak - bucket.equity) / bucket.peak * 100);
    }
    previousEquity = trade.equity_after;
  }
  return months;
}

const returnShade = value => value == null || isNaN(value) ? ''
  : `background:rgba(${value >= 0 ? '46,189,133' : '224,83,61'},` +
    `${Math.min(Math.abs(value) / RETURN_SCALE, 0.62)})`;

const drawdownShade = value => value == null || isNaN(value) ? ''
  : `background:rgba(224,83,61,${Math.min(value / DD_SCALE, 0.65)})`;

export function renderMonthly() {
  const months = monthlyBuckets(store.trades, store.stats.initial_capital);
  const buckets = [...months.values()];
  if (!buckets.length) {
    $('#mmBody').innerHTML = '<p class="muted">No trades to summarise.</p>';
    return;
  }
  const years = [...new Set(buckets.map(b => b.year))].sort();
  const returns = buckets.map(monthReturn);
  const drawdowns = buckets.map(b => b.maxDrawdown);

  $('#mmBody').innerHTML =
    kpis(returns, drawdowns) +
    '<h3>Monthly return %</h3>' + grid(months, years, 'return') +
    '<h3>Monthly max drawdown %</h3>' + grid(months, years, 'drawdown');
}

const monthReturn = bucket => bucket.start > 0 ? bucket.pnl / bucket.start * 100 : 0;

function grid(months, years, mode) {
  const isReturn = mode === 'return';
  const total = isReturn ? 'Year' : 'Max';
  let html = `<table class="mtab"><tr><th></th>` +
    MONTH_NAMES.map(m => `<th>${m}</th>`).join('') + `<th>${total}</th></tr>`;
  for (const year of years) {
    let row = `<tr><td class="yr">${year}</td>`;
    let yearStart = null, yearEnd = null, yearDrawdown = 0;
    for (let month = 0; month < 12; month++) {
      const bucket = months.get(year + '-' + month);
      if (!bucket) { row += '<td></td>'; continue; }
      if (isReturn) {
        const value = monthReturn(bucket);
        row += `<td style="${returnShade(value)}">${fmt(value, 1)}</td>`;
      } else {
        row += `<td style="${drawdownShade(bucket.maxDrawdown)}">${fmt(bucket.maxDrawdown, 1)}</td>`;
      }
      if (yearStart == null) yearStart = bucket.start;
      yearEnd = bucket.equity;
      yearDrawdown = Math.max(yearDrawdown, bucket.maxDrawdown);
    }
    if (isReturn) {
      const yearReturn = (yearStart != null && yearStart > 0)
        ? (yearEnd / yearStart - 1) * 100 : null;
      row += `<td class="tot" style="${returnShade(yearReturn)}">` +
             `${yearReturn == null ? '' : fmt(yearReturn, 1)}</td></tr>`;
    } else {
      row += `<td class="tot" style="${drawdownShade(yearDrawdown)}">` +
             `${fmt(yearDrawdown, 1)}</td></tr>`;
    }
    html += row;
  }
  return html + '</table>';
}

function kpis(returns, drawdowns) {
  const positive = returns.filter(r => r > 0).length;
  const kpi = (label, value, cls = '') =>
    `<div class="mm-kpi"><div class="k">${label}</div><div class="v ${cls}">${value}</div></div>`;
  return '<div class="mm-sub">' +
    kpi('Months', returns.length) +
    kpi('Positive', fmt(positive / returns.length * 100, 0) + '%') +
    kpi('Best month', '+' + fmt(Math.max(...returns), 1) + '%', 'pos') +
    kpi('Worst month', fmt(Math.min(...returns), 1) + '%', 'neg') +
    kpi('Worst month DD', fmt(Math.max(...drawdowns), 1) + '%', 'neg') +
    '</div>';
}
