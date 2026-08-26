/* The Trades tab: filtering, sorting, and clicking a row to jump to the chart. */

import {$, $$} from '../core/dom.js';
import {emit, on, EVENTS} from '../core/bus.js';
import {fmt, shortDt, signClass} from '../core/format.js';
import {store} from '../data/store.js';

/* Exit reasons, shortened to what fits a rail-width column. The full word is
   still on the chart tooltip. */
const REASON_LABEL = {
  TrendChange: 'TREND', TimeExit: 'TIME', EndOfData: 'EOD', DataGap: 'GAP',
};

/* Nearly every trade closes on its entry day (mean hold is a few 5m bars), so
   repeating the whole date in the exit column buys nothing and costs a
   column's width. Show the time alone on a same-day exit, and month-day plus
   time when the trade crossed midnight — the year is already in the entry. */
const exitCell = trade => {
  const entry = String(trade.entry_dt || ''), exit = String(trade.exit_dt || '');
  if (!exit) return '';
  return exit.slice(0, 10) === entry.slice(0, 10)
    ? exit.slice(11, 16)
    : `<span class="muted">${exit.slice(5, 10)}</span> ${exit.slice(11, 16)}`;
};

const FILTERS = {
  all: () => true,
  long: t => t.direction === 'long',
  short: t => t.direction === 'short',
  win: t => t.pnl > 0,
  loss: t => t.pnl < 0,
};

// column order in the table head -> the trade field each one sorts by
const SORT_KEYS = ['id', 'direction', 'entry_time', 'entry_price', 'exit_time',
                   'exit_price', 'exit_reason', 'bars_held', 'pnl', 'equity_after'];

export class TradeTable {
  constructor() {
    this.filter = 'all';
    this.sortKey = 'id';
    this.sortDirection = 1;
    this.selectedId = null;
    on(EVENTS.TRADE_SELECTED, ({id}) => this.highlight(id));
  }

  /** Wire the controls once; the rows are re-bound on every render. */
  wire() {
    $$('#filters button').forEach(button => {
      button.onclick = () => {
        $$('#filters button').forEach(other => other.classList.remove('active'));
        button.classList.add('active');
        this.filter = button.dataset.f;
        this.render();
      };
    });
    $$('#tradeTable thead th').forEach((header, index) => {
      header.onclick = () => this.sortBy(SORT_KEYS[index]);
    });
  }

  sortBy(key) {
    if (this.sortKey === key) this.sortDirection *= -1;
    else { this.sortKey = key; this.sortDirection = 1; }
    this.render();
  }

  visibleTrades() {
    const keep = FILTERS[this.filter] || FILTERS.all;
    return store.trades.filter(keep).sort((a, b) => {
      const left = a[this.sortKey], right = b[this.sortKey];
      if (typeof left === 'string') return this.sortDirection * left.localeCompare(right);
      return this.sortDirection * ((left > right) - (left < right));
    });
  }

  render() {
    const trades = this.visibleTrades();
    $('#tradeCount').textContent = `${trades.length} shown`;
    $('#tradeTable tbody').innerHTML = trades.map(t => this._row(t)).join('');
    $$('#tradeTable tbody tr').forEach(row => {
      row.onclick = () => emit(EVENTS.TRADE_SELECTED, {id: Number(row.dataset.id), fromTable: true});
    });
  }

  highlight(id) {
    this.selectedId = id;
    $$('#tradeTable tbody tr').forEach(row =>
      row.classList.toggle('sel', Number(row.dataset.id) === id));
  }

  _row(trade) {
    const long = trade.direction === 'long';
    return `<tr data-id="${trade.id}" class="${trade.id === this.selectedId ? 'sel' : ''}">
      <td>${trade.id}</td>
      <td class="l"><span class="tag ${long ? 'long' : 'short'}">${long ? 'LONG' : 'SHORT'}</span></td>
      <td class="l">${shortDt(trade.entry_dt)}</td>
      <td class="col-px">${fmt(trade.entry_price)}</td>
      <td class="l">${exitCell(trade)}</td>
      <td class="col-px">${fmt(trade.exit_price)}</td>
      <td><span class="tag ${trade.exit_reason.toLowerCase()}">${
        REASON_LABEL[trade.exit_reason] || trade.exit_reason}</span></td>
      <td class="col-opt">${trade.bars_held}</td>
      <td class="${signClass(trade.pnl)}">${(trade.pnl >= 0 ? '+' : '') + fmt(trade.pnl)}</td>
      <td class="col-opt">${fmt(trade.equity_after)}</td>
    </tr>`;
  }
}
