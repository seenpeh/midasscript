/* The "Edit & Run" drawer: reads strategy parameters out of the form and posts
   a new backtest.

   PARAM_FIELDS is the contract with the server: every name here is a field of
   `Params` in midas/config/params.py, and the input for it has id `f_<name>`. */

import {$, field, toast} from '../core/dom.js';
import {store} from '../data/store.js';
import {fetchDefaultParams} from '../data/api.js';

export const PARAM_FIELDS = [
  'ema_fast_len', 'ema_slow_len', 'trend_close_enable',
  't1_en', 't1_n', 't1_tr_mult', 't1_m', 't1_rr_pri', 't1_rr_alt', 't1_risk',
  't2_en', 't2_c', 't2_n', 't2_tr_mult', 't2_m', 't2_rr_pri', 't2_rr_alt', 't2_risk',
  't3_en', 't3_n', 't3_tr_mult', 't3_m', 't3_rr_pri', 't3_rr_alt', 't3_risk',
  'dyn_sl_enable', 'max_size_candle', 'min_stop_loss_ratio',
  'dll_enable', 'dll_loss_pct',
  'session_filter_enable', 'sess_start_hr', 'sess_end_hr',
  'pyramiding',
  'spread',
];

export class SettingsDrawer {
  constructor(runner) {
    this.runner = runner;          // (body, label) => Promise, provided by main.js
  }

  wire() {
    $('#btnEdit').onclick = () => this.open();
    $('#btnClose').onclick = () => this.close();
    $('#btnReset').onclick = () => this.populate();
    $('#btnDefaults').onclick = () => this.resetToDefaults();
    $('#btnApply').onclick = () => this.apply();
    $('#f_spread').oninput = () => this.updateSpreadHint();
  }

  open() {
    this.populate();
    $('#drawer').classList.add('open');
    $('#scrim').classList.add('open');
  }

  close() {
    $('#drawer').classList.remove('open');
    $('#scrim').classList.remove('open');
  }

  /** Fill the form from the last run's parameters. */
  populate() {
    const params = (store.meta && store.meta.params) || {};
    const {start, end, capital, chartDays} = store.lastRun;
    $('#f_start').value = start || '';
    $('#f_end').value = end || '';
    $('#f_capital').value = capital;
    $('#f_chart_days').value = chartDays;
    this._writeParams(params);
  }

  /** Reset only the strategy parameters, keeping the dates and capital. */
  async resetToDefaults() {
    if (!store.defaultParams) store.defaultParams = await fetchDefaultParams();
    if (!store.defaultParams) { toast('Defaults not loaded yet'); return; }
    this._writeParams(store.defaultParams);
    toast('Strategy params reset to defaults');
  }

  /** The request body for POST /api/run. */
  read() {
    const params = {};
    for (const name of PARAM_FIELDS) {
      const input = field(name);
      if (!input) continue;
      if (input.type === 'checkbox') { params[name] = input.checked; continue; }
      const value = input.value.trim();
      if (value !== '') params[name] = Number(value);
    }
    return {
      start: $('#f_start').value.trim() || null,
      end: $('#f_end').value.trim() || null,
      capital: Number($('#f_capital').value) || 10000,
      chart_days: Number($('#f_chart_days').value) || 730,
      params,
    };
  }

  async apply() {
    const body = this.read();
    store.lastRun = {capital: body.capital, chartDays: body.chart_days,
                     start: body.start || '', end: body.end || ''};
    $('#btnApply').disabled = true;
    await this.runner(body);
    this.close();
    $('#btnApply').disabled = false;
  }

  updateSpreadHint() {
    const hint = $('#spreadHint');
    if (!hint) return;
    const spread = parseFloat($('#f_spread').value);
    const half = isFinite(spread) ? spread / 2 : null;
    hint.textContent =
      (half == null ? '' : `Each fill moves $${half.toFixed(2)} against the trade · `) +
      `round-turn cost = one full spread ($${isFinite(spread) ? spread.toFixed(2) : '0.20'}).`;
  }

  _writeParams(params) {
    for (const name of PARAM_FIELDS) {
      const input = field(name);
      if (!input) continue;
      const value = params[name];
      if (input.type === 'checkbox') input.checked = !!value;
      else input.value = (value == null ? '' : value);
    }
    this.updateSpreadHint();
  }
}
