/* The candle-size comparison pane: each bar's body (or true range) divided by
   the average of the previous n bars — the same ratio the strategy's triggers
   test, drawn so you can see where a "big candle" actually is. */

import {$} from '../core/dom.js';
import {baseChartOptions, linkTimeScales, COLORS} from './theme.js';

export const BIG_CANDLE_RATIO = 2;

export function trueRanges(candles) {
  const out = [];
  let previousClose = null;
  for (const [, , high, low, close] of candles) {
    out.push(previousClose == null ? high - low
      : Math.max(high - low, Math.abs(high - previousClose), Math.abs(low - previousClose)));
    previousClose = close;
  }
  return out;
}

/** Histogram points: ratio of each bar's metric to the average of the previous
    `lookback` bars. Bars without a full lookback show as an empty grey bar. */
export function sizeRatios(candles, metric, lookback) {
  const values = metric === 'tr' ? trueRanges(candles)
                                 : candles.map(r => Math.abs(r[4] - r[1]));
  return candles.map((candle, i) => {
    let ratio = null;
    if (i >= lookback) {
      let sum = 0;
      for (let k = 1; k <= lookback; k++) sum += values[i - k];
      const average = sum / lookback;
      ratio = average > 0 ? values[i] / average : null;
    }
    const value = ratio == null ? 0 : ratio;
    return {
      time: candle[0], value,
      color: ratio == null ? COLORS.dim
           : value >= BIG_CANDLE_RATIO ? COLORS.up
           : value >= 1 ? COLORS.mid : COLORS.dim,
    };
  });
}

/** Owns the pane's chart instance and its controls. */
export class SizeComparePane {
  constructor() {
    this.visible = false;
    this.metric = 'body';
    this.lookback = 4;
    this.chart = null;
    this.series = null;
  }

  toggle(visible) { this.visible = visible; }

  setMetric(metric) { this.metric = metric; }

  setLookback(n) { this.lookback = Math.max(1, Math.min(200, Math.round(n) || 4)); }

  destroy() {
    if (!this.chart) return;
    try { this.chart.remove(); } catch { /* already gone */ }
    this.chart = null;
    this.series = null;
  }

  /** (Re)draw for the current view, linked to the price chart's time axis. */
  render(view, priceChart) {
    const pane = $('#sizecmp');
    $('#btnCmp') && $('#btnCmp').classList.toggle('on', this.visible);
    if (!this.visible) {
      this.destroy();
      pane.style.display = 'none';
      return;
    }
    pane.style.display = 'flex';
    if (!this.chart) this._create(priceChart);
    this.series.setData(sizeRatios(view.candles, this.metric, this.lookback));
    $('#cmpLabel').textContent =
      `${this.metric === 'tr' ? 'True range' : 'Body'} ÷ avg of last ${this.lookback}`;
    $('#cmpN').value = this.lookback;
    $('#cmpMetricBody').classList.toggle('on', this.metric === 'body');
    $('#cmpMetricTr').classList.toggle('on', this.metric === 'tr');
  }

  _create(priceChart) {
    this.chart = LightweightCharts.createChart($('#cmpChartHost'),
      {...baseChartOptions(), autoSize: true});
    this.series = this.chart.addHistogramSeries(
      {base: 0, priceFormat: {type: 'price', precision: 2, minMove: 0.01}});
    this.series.createPriceLine({price: BIG_CANDLE_RATIO, color: COLORS.up, lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: '×2'});
    this.series.createPriceLine({price: 1, color: COLORS.neutral, lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: '×1'});
    linkTimeScales(priceChart, this.chart);
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) this.chart.timeScale().setVisibleLogicalRange(range);
  }
}
