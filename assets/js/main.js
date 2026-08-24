/* Boot and wiring: the only module that knows all the others exist.

   Everything else is either pure logic (timeframes, smoothing, markers,
   monthly buckets), a view that renders one region, or the API client. This
   file assembles them and owns the "run a backtest, then redraw" cycle. */

import {$, $$, toast} from './core/dom.js';
import {on, EVENTS} from './core/bus.js';
import {store} from './data/store.js';
import {fetchDefaultParams, runBacktest} from './data/api.js';
import {ChartView} from './chart/chartView.js';
import {renderHeader, renderMeta} from './panels/header.js';
import {renderStats} from './panels/stats.js';
import {TradeTable} from './panels/trades.js';
import {renderMonthly} from './panels/monthly.js';
import {SettingsDrawer} from './panels/settings.js';
import {OptimizerDrawer} from './panels/optimizer.js';

const chart = new ChartView();
const trades = new TradeTable();
const settings = new SettingsDrawer(runAndRedraw);
const optimizer = new OptimizerDrawer(settings, runAndRedraw);

/** Redraw every region from the current store contents. */
function renderAll() {
  renderHeader(chart.view);
  chart.render();
  renderStats();
  trades.render();
}

/** POST a run, wait for the server, then reload the artefacts it wrote. */
async function runAndRedraw(body, label) {
  $('#busy').classList.add('on');
  $('#busyMsg').textContent = label || 'Running backtest…';
  try {
    const result = await runBacktest(body);
    $('#busyMsg').textContent = `Loading new data (server ran in ${result.took}s)…`;
    await store.reload({bust: true});          // cache-bust: the files just changed
    renderAll();
    toast(`Backtest done in ${result.took}s — ` +
          `${result.stats.total_trades.toLocaleString()} trades`);
  } catch (error) {
    console.error(error);
    toast('Run failed: ' + error.message);
  } finally {
    $('#busy').classList.remove('on');
  }
}

function wireShell() {
  trades.wire();
  settings.wire();
  optimizer.wire();

  $$('.tabs button').forEach(button => {
    button.onclick = () => {
      $$('.tabs button').forEach(other => other.classList.remove('active'));
      button.classList.add('active');
      $('#tab-trades').style.display = button.dataset.tab === 'trades' ? 'block' : 'none';
      $('#tab-stats').style.display = button.dataset.tab === 'stats' ? 'block' : 'none';
    };
  });

  $('#btnMonthly').onclick = () => {
    if (!store.results) { toast('No results loaded yet'); return; }
    renderMonthly();
    $('#monthlyModal').classList.add('open');
  };
  const closeMonthly = () => $('#monthlyModal').classList.remove('open');
  $('#mmClose').onclick = closeMonthly;
  $('#monthlyModal').onclick = event => {
    if (event.target.id === 'monthlyModal') closeMonthly();
  };

  const closeDrawers = () => { settings.close(); optimizer.close(); };
  $('#scrim').onclick = closeDrawers;
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { closeDrawers(); closeMonthly(); }
  });

  // a click in the table selects the trade on the chart; the chart echoes the
  // selection back so the row highlights (see core/bus.js)
  on(EVENTS.TRADE_SELECTED, ({id, fromTable}) => {
    if (fromTable) chart.selectTrade(id);
  });
  on(EVENTS.DATA_RELOADED, view => renderMeta(view));
}

async function boot() {
  try {
    await store.reload();
    wireShell();
    renderAll();
    store.defaultParams = await fetchDefaultParams();
    settings.populate();   // seed the fields so the optimizer can read them
  } catch (error) {
    $('#err').style.display = 'flex';
    $('#errDetail').textContent = 'Detail: ' + error.message;
    console.error(error);
  }
}

boot();
