/* The walk-forward optimisation drawer: configure, estimate, run, read results.

   The run itself happens on the server in a background thread; this polls
   /api/optimize/status until it reports done. */

import {$, toast} from '../core/dom.js';
import {fmt, fmtInt, signed} from '../core/format.js';
import {estimateOptimization, optimizationStatus, startOptimization} from '../data/api.js';
import {store} from '../data/store.js';

const GROUPS = ['t1', 't2', 't3', 'exposure', 'trend', 'dynsl'];
const POLL_MS = 1200;
const ROBUST_EFFICIENCY = 0.5;
const ROBUST_PROFIT_FACTOR = 1.1;

export class OptimizerDrawer {
  constructor(settingsDrawer, runner) {
    this.settings = settingsDrawer;    // supplies the non-tuned parameters
    this.runner = runner;              // (body, label) => Promise
    this.poll = null;
  }

  wire() {
    $('#btnOpt').onclick = () => this.open();
    $('#optClose').onclick = () => this.close();
    $('#optEstimateBtn').onclick = () => this.estimate();
    $('#optRunBtn').onclick = () => this.run();
  }

  open() {
    $('#optDrawer').classList.add('open');
    $('#scrim').classList.add('open');
  }

  close() {
    $('#optDrawer').classList.remove('open');
    $('#scrim').classList.remove('open');
  }

  /** The request body for both /api/optimize endpoints. */
  body() {
    const objective = document.querySelector('input[name=obj]:checked');
    return {
      groups: GROUPS.filter(name => $('#og_' + name).checked),
      objective_metric: (objective && objective.value) || 'calmar',
      base_start: $('#o_base').value.trim() || '2024-01-01',
      base_end: $('#o_base_end').value.trim() || null,
      capital: +$('#o_capital').value || 10000,
      max_dd_pct: +$('#o_maxdd').value || 30,
      n_parts: Math.max(2, +$('#o_parts').value || 5),
      trials: +$('#o_trials').value || 80,
      final_trials: +$('#o_final').value || 120,
      // non-tuned parameters come from the current Edit & Run settings
      params: this.settings.read().params,
    };
  }

  async estimate() {
    const body = this.body();
    if (!body.groups.length) { toast('Select at least one parameter group'); return; }
    $('#optEstimate').textContent = 'Estimating…';
    try {
      const result = await estimateOptimization(body);
      $('#optEstimate').innerHTML =
        `⏱ ~${result.est_seconds}s (~${(result.est_seconds / 60).toFixed(1)} min) · ` +
        `${result.n_folds} folds · ${fmtInt(result.total_evals)} backtests · ` +
        `${result.per_eval_s}s each`;
    } catch (error) {
      $('#optEstimate').textContent = 'Estimate failed: ' + error.message;
    }
  }

  async run() {
    const body = this.body();
    if (!body.groups.length) { toast('Select at least one parameter group'); return; }
    this._setBusy(true);
    $('#optResults').innerHTML = '';
    $('#optProgWrap').style.display = 'block';
    $('#optBarFill').style.width = '0%';
    $('#optProgText').textContent = 'Starting…';
    try {
      await startOptimization(body);
      this.poll = setInterval(() => this._poll(), POLL_MS);
    } catch (error) {
      toast('Optimize failed: ' + error.message);
      this._setBusy(false);
    }
  }

  async _poll() {
    let status;
    try {
      status = await optimizationStatus();
    } catch {
      return;                                  // transient; the next tick retries
    }
    const progress = status.progress || {};
    if (progress.pct != null) $('#optBarFill').style.width = progress.pct + '%';
    let text = progress.msg || progress.phase || '';
    if (progress.trials_done != null) {
      text += `  (${progress.trials_done}/${progress.trials_total} backtests)`;
    }
    $('#optProgText').textContent = text;

    if (status.error) {
      this._stopPolling();
      $('#optProgText').textContent = 'Error: ' + status.error;
      toast('Optimization error: ' + status.error);
      return;
    }
    if (status.done && status.result) {
      this._stopPolling();
      $('#optBarFill').style.width = '100%';
      $('#optProgText').textContent = 'Done in ' + (status.result.elapsed_s || '?') + 's';
      this.renderResults(status.result);
    }
  }

  _stopPolling() {
    clearInterval(this.poll);
    this.poll = null;
    this._setBusy(false);
  }

  _setBusy(busy) {
    $('#optRunBtn').disabled = busy;
    $('#optEstimateBtn').disabled = busy;
  }

  renderResults(result) {
    $('#optResults').innerHTML =
      headline(result) + oosGrid(result) + verdict(result) +
      foldTable(result) + recommendation(result);
    $('#optApply').onclick = () => this.applyRecommended(result);
  }

  /** Re-run the backtest with the recommended parameters over the tuned window. */
  async applyRecommended(result) {
    this.close();
    const config = result.config;
    const end = (config.base_end && config.base_end !== '(data end)') ? config.base_end : null;
    store.lastRun = {...store.lastRun, start: config.base_start, end: end || '',
                     capital: config.capital};
    await this.runner({
      start: config.base_start, end,
      capital: config.capital, chart_days: store.lastRun.chartDays || 730,
      params: result.recommended.params,
    }, 'Applying recommended params…');
  }
}

// ---------------------------------------------------------------------------
// Result rendering
// ---------------------------------------------------------------------------
const statCell = (label, value, cls = '') =>
  `<div class="stat"><div class="k">${label}</div><div class="v ${cls}">${value}</div></div>`;

const drawdownClass = (dd, cap) => dd <= cap ? 'pos' : (dd <= cap * 1.6 ? '' : 'neg');

function headline(result) {
  const active = (result.config.active_triggers || []).join(', ');
  return `<p class="opt-note tight-bottom">Active triggers: <b>${active}</b> ` +
         `· objective: ${result.config.objective}</p>` +
         '<div class="wf-head">Walk-forward OUT-OF-SAMPLE (the honest estimate)</div>';
}

function oosGrid(result) {
  const oos = result.wf_oos, cap = result.config.max_dd_pct;
  const pf = oos.profit_factor, metric = result.config.objective_metric;
  return '<div class="stat-grid">' +
    statCell('OOS return', signed(oos.return_pct) + '%', oos.return_pct >= 0 ? 'pos' : 'neg') +
    statCell('OOS max DD', fmt(oos.max_drawdown_pct) + '%',
             oos.max_drawdown_pct <= cap ? 'pos' : 'neg') +
    statCell('Profit factor', pf == null ? '—' : fmt(pf, 2),
             pf >= ROBUST_PROFIT_FACTOR ? 'pos' : (pf >= 1 ? '' : 'neg')) +
    statCell('WF efficiency', fmt(result.wf_efficiency, 2),
             result.wf_efficiency >= ROBUST_EFFICIENCY ? 'pos' : 'neg') +
    statCell('OOS trades', fmtInt(oos.total_trades)) +
    statCell('Win rate', fmt(oos.win_rate) + '%') +
    '</div><div class="stat-grid">' +
    statCell('OOS Sharpe', fmt(oos.sharpe, 2), metric === 'sharpe' ? 'pos' : '') +
    statCell('OOS Sortino', fmt(oos.sortino, 2), metric === 'sortino' ? 'pos' : '') +
    statCell('OOS Calmar', fmt(oos.calmar, 2), metric === 'calmar' ? 'pos' : '') +
    '</div>';
}

function verdict(result) {
  const pf = result.wf_oos.profit_factor;
  let badge;
  if (result.wf_efficiency >= ROBUST_EFFICIENCY && pf >= ROBUST_PROFIT_FACTOR) {
    badge = '<span class="wf-badge wf-good">robust</span>';
  } else if (pf >= 1.0) {
    badge = '<span class="wf-badge wf-warn">thin / fragile edge</span>';
  } else {
    badge = '<span class="wf-badge wf-bad">no real OOS edge</span>';
  }
  return `<p class="opt-note">Verdict: ${badge} — OOS profit factor ` +
    `${pf == null ? '—' : fmt(pf, 2)}, WF-efficiency ${fmt(result.wf_efficiency, 2)} ` +
    `(OOS÷IS return). Low efficiency ⇒ the fit doesn't generalise.</p>`;
}

function foldTable(result) {
  const cap = result.config.max_dd_pct;
  const rows = result.folds.map(fold =>
    `<tr><td>${fold.fold}</td>` +
    `<td>${fold.oos_start.slice(2)}→${fold.oos_end.slice(2)}</td>` +
    `<td>${fmt(fold.is_return_pct)}</td>` +
    `<td class="${fold.oos_return_pct >= 0 ? 'pos' : 'neg'}">${fmt(fold.oos_return_pct)}</td>` +
    `<td class="${drawdownClass(fold.oos_dd_pct, cap)}">${fmt(fold.oos_dd_pct)}</td>` +
    `<td>${fmtInt(fold.oos_trades)}</td></tr>`).join('');
  return '<div class="wf-head">Per-fold IS vs OOS</div>' +
    '<table class="brk"><tr><td>#</td><td>OOS window</td><td>IS%</td><td>OOS%</td>' +
    `<td>OOS DD%</td><td>Trades</td></tr>${rows}</table>`;
}

function recommendation(result) {
  const inSample = result.recommended.in_sample_full;
  const values = Object.entries(result.recommended.optimised_values).map(([key, value]) =>
    `<div><span>${key}</span><b>` +
    `${typeof value === 'number' && !Number.isInteger(value) ? fmt(value, 2) : value}</b></div>`
  ).join('');
  return '<div class="wf-head">Recommended params (full-window fit)</div>' +
    `<p class="opt-note">In-sample full-window: ${fmt(inSample.return_pct)}% return · ` +
    `${fmt(inSample.max_drawdown_pct)}% DD · PF ${fmt(inSample.profit_factor, 2)} · ` +
    `${fmtInt(inSample.total_trades)} trades.<br>` +
    '<b>Expect the OOS numbers above, not these</b> — the full-window fit is optimistic.</p>' +
    `<div class="pgrid">${values}</div>` +
    '<button class="opt-apply" id="optApply">✓ Apply &amp; backtest from ' +
    `${result.config.base_start}</button>`;
}
