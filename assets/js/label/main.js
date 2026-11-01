/* Boot and wiring for the labelling page.

   One candle chart, one overlay of rectangles, one rectangle tool, one
   homework bar. The higher timeframes are aggregated from the same 5-minute
   file the viewer uses (`assets/js/chart/timeframes.js`), so switching
   timeframe changes only what is drawn — and which labels apply to it, since
   a label belongs to the timeframe it was drawn on.

   Labels live in sqlite behind /api/labels; this file is the only one here
   that talks to it. */

import {$, $$, toast} from '../core/dom.js';
import {buildView, barIndexAt} from '../chart/timeframes.js';
import {baseChartOptions, COLORS} from '../chart/theme.js';
import {LabelBoxes} from './boxes.js';
import {RectangleTool} from './draw.js';
import {renderHomework} from './homework.js';

const CANDLE_FILE = '5m_candles_chart.json';
const TIMEFRAMES = ['5m', '1h', '4h', '1D'];   // the four with a daily quota
const RESUME_BARS = 180;                       // bars on screen when resuming

const boxes = new LabelBoxes();
let dataset = {candles: [], holes: []};
let labels = [];
let quota = {};
let timeframe = '5m';
let view = null;
let chart = null;
let series = null;
let tool = null;
let pending = null;

// -- server ------------------------------------------------------------------
async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || ('HTTP ' + response.status));
  }
  return payload;
}

// -- drawing the chart -------------------------------------------------------
function redrawTimeframe({resume = true} = {}) {
  view = buildView(timeframe, dataset);
  series.setData(view.candles.map(
    row => ({time: row[0], open: row[1], high: row[2], low: row[3], close: row[4]})));
  boxes.setData(view, labels);
  $$('#tfSeg button').forEach(button =>
    button.classList.toggle('on', button.dataset.tf === timeframe));
  renderBar();
  if (resume) resumeWhereHeLeftOff();
}

/** Put the last labelled candle at the left edge, so the day starts where the
    last one stopped. With nothing labelled yet, start at the oldest candles.
    Deferred a frame: autoSize's first resize lands after this and would drag
    the range back to the tail of 281,922 candles. */
function resumeWhereHeLeftOff() {
  const mine = labels.filter(label => label.tf === timeframe);
  const last = mine.reduce((max, label) => Math.max(max, label.end_ts), 0);
  const index = last ? barIndexAt(view, last) : 0;
  requestAnimationFrame(() => chart.timeScale().setVisibleLogicalRange(
    {from: Math.max(-2, index - 20), to: index + RESUME_BARS}));
}

function renderBar() {
  renderHomework($('#homework'), {labels, quota, timeframe, pending});
}

// -- labels ------------------------------------------------------------------
async function addLabel({trend, i0, i1}) {
  const body = {tf: timeframe, trend, bars: i1 - i0 + 1,
                start_ts: view.candles[i0][0], end_ts: view.candles[i1][0]};
  try {
    const {label} = await postJson('/api/labels', body);
    labels.push(label);
    boxes.setData(view, labels);
    renderBar();
  } catch (error) {
    toast(error.message);
  }
}

async function removeLabel(box) {
  try {
    await postJson('/api/labels/delete', {id: box.id});
    labels = labels.filter(label => label.id !== box.id);
    boxes.select(null);
    boxes.setData(view, labels);
    renderBar();
    toast('Label removed');
  } catch (error) {
    toast(error.message);
  }
}

// -- wiring ------------------------------------------------------------------
function wire() {
  $('#tfSeg').innerHTML = TIMEFRAMES.map(tf =>
    `<button data-tf="${tf}"${tf === timeframe ? ' class="on"' : ''}>${tf}</button>`).join('');
  $$('#tfSeg button').forEach(button => {
    button.onclick = () => {
      if (button.dataset.tf === timeframe) return;
      timeframe = button.dataset.tf;
      tool.cancel();
      redrawTimeframe();
    };
  });

  $$('#trendSeg button').forEach(button => {
    button.onclick = () => {
      $$('#trendSeg button').forEach(other => other.classList.remove('on'));
      button.classList.add('on');
      tool.setTrend(button.dataset.trend);
    };
  });

  $('#btnResume').onclick = resumeWhereHeLeftOff;
  $('#btnFit').onclick = () => chart.timeScale().fitContent();
  $('#btnDelete').onclick = () => {
    const box = boxes.selected;
    if (!box) { toast('Click a rectangle first'); return; }
    removeLabel(box);
  };
}

async function boot() {
  try {
    const [candles, stored] = await Promise.all([
      getJson(CANDLE_FILE), getJson('/api/labels')]);
    dataset = candles;
    labels = stored.labels;
    quota = stored.quota;
    $('#range').textContent =
      `${candles.count.toLocaleString()} 5m candles · ${candles.from} → ${candles.to} UTC`;

    chart = LightweightCharts.createChart($('#chart'),
      {...baseChartOptions(), autoSize: true});
    series = chart.addCandlestickSeries({
      upColor: COLORS.up, downColor: COLORS.down, borderVisible: false,
      wickUpColor: COLORS.up, wickDownColor: COLORS.down});
    series.priceScale().applyOptions({scaleMargins: {top: 0.08, bottom: 0.12}});
    series.attachPrimitive(boxes);

    tool = new RectangleTool({chart, boxes, onAdd: addLabel, onDelete: removeLabel,
      onPending: bars => { pending = bars; renderBar(); }});
    wire();
    redrawTimeframe();
  } catch (error) {
    $('#err').style.display = 'flex';
    $('#errDetail').textContent = 'Detail: ' + error.message;
    console.error(error);
  }
}

boot();
