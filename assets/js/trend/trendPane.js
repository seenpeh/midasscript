/* The fuzzy-trend pane: the 0..1 trend number, on 5m and on 1h, under the
   price chart and sharing its time axis.

   Both lines are always computed on THEIR OWN timeframe — the 5m line from 5m
   bars, the 1h line from 1h bars — and then projected onto whatever timeframe
   the price chart happens to be showing (each chart bar takes the last trend
   value known at its open). So switching the price chart between 5m and 1D
   changes the resolution you view them at, never the numbers themselves. */

import {$} from '../core/dom.js';
import {baseChartOptions, linkTimeScales, COLORS} from '../chart/theme.js';
import {MAX_BARS, MAX_LEVEL} from './smoothing.js';
import {NEUTRAL, TREND_DEFAULTS, trendSeries} from './fuzzy.js';

/** Sample `points` (time-ordered) at each of `candles`' open times, holding the
    last known value forward. Both are ascending, so one pass does it. */
export function alignToBars(points, candles) {
  const out = [];
  let index = 0, value = NEUTRAL;
  for (const candle of candles) {
    const time = candle[0];
    while (index < points.length && points[index].time <= time) value = points[index++].value;
    out.push({time, value});
  }
  return out;
}

export class TrendPane {
  constructor() {
    this.visible = false;
    this.level = TREND_DEFAULTS.smooth;
    this.custom = {back: 5, fwd: 5};   // the typed window, when isCustom
    this.isCustom = false;
    this.gain = TREND_DEFAULTS.gain;
    this.showFast = true;      // the 5m line
    this.showSlow = true;      // the 1h line
    this.chart = null;
    this.series = {};
  }

  toggle(visible) { this.visible = visible; }
  setLevel(level) { this.level = Math.max(0, Math.min(MAX_LEVEL, Math.round(level) || 0)); }
  setCustom(on) { this.isCustom = !!on; }

  /** Custom window: `back` bars behind each bar, `fwd` ahead — same meaning as
      the price line's m·n control. */
  setWindow(back, fwd) {
    this.custom = {
      back: Math.max(0, Math.min(MAX_BARS, Math.round(back) || 0)),
      fwd: Math.max(0, Math.min(MAX_BARS, Math.round(fwd) || 0)),
    };
  }

  /** What the trend maths takes: a preset level, or the typed window. */
  smoothSetting() { return this.isCustom ? this.custom : this.level; }

  setGain(gain) { this.gain = Math.max(0.5, Math.min(20, +gain || TREND_DEFAULTS.gain)); }

  setLine(which, on) {
    if (which === 'fast') this.showFast = on; else this.showSlow = on;
    if (this.series.fast) this.series.fast.applyOptions({visible: this.showFast});
    if (this.series.slow) this.series.slow.applyOptions({visible: this.showSlow});
    this._syncControls();
  }

  destroy() {
    if (!this.chart) return;
    try { this.chart.remove(); } catch { /* already gone */ }
    this.chart = null;
    this.series = {};
  }

  /** (Re)draw for the current view. `sources` is {fast, slow}: the 5m and 1h
      candle rows the two lines are computed from. */
  render(view, priceChart, sources) {
    const pane = $('#trend');
    if (!pane) return;
    $('#btnTrend') && $('#btnTrend').classList.toggle('on', this.visible);
    if (!this.visible) {
      this.destroy();
      pane.style.display = 'none';
      return;
    }
    pane.style.display = 'flex';
    if (!this.chart) this._create(priceChart);
    this._setData(view, sources);
    this._syncControls();
  }

  _setData(view, sources) {
    const options = {smooth: this.smoothSetting(), gain: this.gain};
    for (const [key, candles] of [['fast', sources.fast], ['slow', sources.slow]]) {
      this.series[key].setData(
        alignToBars(trendSeries(candles, options), view.candles));
    }
  }

  _create(priceChart) {
    this.chart = LightweightCharts.createChart($('#trendChartHost'),
      {...baseChartOptions(), autoSize: true});
    // the axis means the same thing at every zoom, so it is pinned to 0..1
    const fixedScale = () => ({priceRange: {minValue: 0, maxValue: 1}});
    const line = (color, visible) => this.chart.addLineSeries({
      color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: true, visible,
      priceFormat: {type: 'price', precision: 2, minMove: 0.01},
      autoscaleInfoProvider: fixedScale});
    this.series.slow = line(COLORS.trendSlow, this.showSlow);
    this.series.fast = line(COLORS.trendFast, this.showFast);
    for (const [price, color, style, title] of [
      [NEUTRAL, COLORS.neutral, LightweightCharts.LineStyle.Dashed, 'sideways'],
      [1, COLORS.up, LightweightCharts.LineStyle.Dotted, 'up'],
      [0, COLORS.down, LightweightCharts.LineStyle.Dotted, 'down'],
    ]) {
      this.series.slow.createPriceLine(
        {price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title});
    }
    linkTimeScales(priceChart, this.chart);
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) this.chart.timeScale().setVisibleLogicalRange(range);
  }

  _syncControls() {
    const set = (id, value) => { const el = $(id); if (el) el.value = value; };
    const text = (id, value) => { const el = $(id); if (el) el.textContent = value; };
    set('#trendLevel', this.level);
    text('#trendLevelVal', this.level);
    set('#trendBack', this.custom.back);
    set('#trendFwd', this.custom.fwd);
    const preset = $('#trendPreset'), window_ = $('#trendWindow');
    if (preset) preset.hidden = this.isCustom;
    if (window_) window_.hidden = !this.isCustom;
    $('#btnTrendCustom') && $('#btnTrendCustom').classList.toggle('on', this.isCustom);
    set('#trendGain', this.gain);
    text('#trendGainVal', this.gain.toFixed(1));
    $('#trendFast') && $('#trendFast').classList.toggle('on', this.showFast);
    $('#trendSlow') && $('#trendSlow').classList.toggle('on', this.showSlow);
  }
}
