/* The price + equity panes: everything that draws, and nothing that decides.

   `ChartView` owns the chart instances and the view state that belongs to them
   (timeframe, price mode, smoothing level, which overlays are on, which trade is
   selected). Panels do not reach inside it — they call `setTimeframe`,
   `selectTrade`, `render` and listen on the bus. */

import {$, $$, toast} from '../core/dom.js';
import {emit, EVENTS} from '../core/bus.js';
import {store} from '../data/store.js';
import {TF_ORDER, buildView, barIndexAt, nearestBar} from './timeframes.js';
import {MAX_BARS, MAX_LEVEL, smoothCloses, smoothWindow} from '../trend/smoothing.js';
import {baseChartOptions, linkTimeScales, COLORS} from './theme.js';
import {buildMarkers, buildTradeIndex} from '../triggers/markers.js';
import {legendHTML, LEGEND_KEYS, tradeTooltipHTML} from './tooltip.js';
import {SizeComparePane} from '../triggers/sizeCompare.js';
import {TrendPane} from '../trend/trendPane.js';

const AUTO_ZOOM_BARS = 180;    // a comfortable default zoom: this many recent bars

export class ChartView {
  constructor() {
    this.timeframe = '5m';
    this.showOhlc = true;           // the two price series are independent:
    this.showLine = false;          // either, both, or (never) neither
    this.smoothLevel = 3;             // preset mode: window is level*2 each side
    this.smoothCustom = {back: 5, fwd: 5};   // custom mode: bars behind/ahead
    this.smoothIsCustom = false;
    this.showTrades = true;
    this.showHoles = true;
    this.showEquity = true;
    this.selectedId = null;
    this.view = {tf: '5m', sec: 300, candles: [], emaFast: [], emaSlow: []};
    this.tradeIndex = new Map();
    this.priceLines = [];
    this.priceLineOwner = null;
    this.sizeCompare = new SizeComparePane();
    this.trend = new TrendPane();
    this.charts = {price: null, equity: null};
    this.series = {};
  }

  get firstTime() { return this.view.candles[0][0]; }
  get lastTime() { return this.view.candles[this.view.candles.length - 1][0]; }
  /* Markers and a trade's price lines live on one series. Candles own them
     whenever they are drawn; the line only takes over when candles are off. */
  get activeSeries() {
    return this.showOhlc ? this.series.candles : this.series.line;
  }

  // -- building ----------------------------------------------------------
  /** Build (or rebuild, after a re-run) both panes from the current store. */
  render() {
    this._teardown();
    $('#price').innerHTML = this._pricePaneHTML();
    $('#equity').innerHTML = '<div class="pane-label">Equity curve</div>';

    const options = baseChartOptions();
    this.charts.price = LightweightCharts.createChart($('#price'),
      {...options, autoSize: true});
    this._createPriceSeries();
    this.view = this._buildView();
    this._setSeriesData();
    this._refreshOverlays();

    this.charts.equity = LightweightCharts.createChart($('#equity'),
      {...options, autoSize: true});
    this._createEquitySeries();

    linkTimeScales(this.charts.price, this.charts.equity);
    this._applyEquityVisible();
    this._wireToolbar();
    this._wireCrosshair();
    this.sizeCompare.render(this.view, this.charts.price);
    this._renderTrend();
    this._syncPriceModeControls();
    emit(EVENTS.DATA_RELOADED, this.view);
    // fit once layout has settled, or autoSize's resize leaves us on the tail
    requestAnimationFrame(() => this.fitAll());
  }

  /** Switch the drawn timeframe: re-aggregate the same 5m file and rebuild every
      derived series. Nothing about the backtest is re-run, because nothing about
      the backtest depends on what you are looking at. The visible range is kept,
      so the switch feels like a zoom rather than a jump. */
  setTimeframe(timeframe) {
    if (timeframe === this.timeframe || !TF_ORDER.includes(timeframe)) return;
    const keep = this.charts.price.timeScale().getVisibleRange();
    this.timeframe = timeframe;
    this.view = this._buildView();
    this._setSeriesData();
    this._refreshOverlays();
    this.series.equity.setData(this._equityData());
    this.sizeCompare.render(this.view, this.charts.price);
    this._renderTrend();
    $$('#tfSeg button').forEach(button =>
      button.classList.toggle('on', button.dataset.tf === this.timeframe));
    emit(EVENTS.DATA_RELOADED, this.view);
    if (keep) {
      try { this.charts.price.timeScale().setVisibleRange(keep); }
      catch { this.fitAll(); }
    }
    this._reselect();
  }

  // -- zoom --------------------------------------------------------------
  fitAll() {
    this.charts.price.timeScale().fitContent();
    this.charts.equity.timeScale().fitContent();
    if (this.sizeCompare.chart) this.sizeCompare.chart.timeScale().fitContent();
    if (this.trend.chart) this.trend.chart.timeScale().fitContent();
    this._setZoomButton('#btnFit');
  }

  autoZoom() {
    const n = this.view.candles.length;
    this.charts.price.timeScale().setVisibleLogicalRange(
      {from: Math.max(-2, n - 1 - AUTO_ZOOM_BARS), to: n - 1 + 6});
    this._setZoomButton('#btnAuto');
  }

  // -- overlays ----------------------------------------------------------
  /** Show or hide one of the price series. The last visible one cannot be
      turned off — an empty price pane is never what the click meant. */
  setPriceSeries(kind, on) {
    const next = {showOhlc: this.showOhlc, showLine: this.showLine};
    next[kind === 'line' ? 'showLine' : 'showOhlc'] = on;
    if (!next.showOhlc && !next.showLine) return;
    this.showOhlc = next.showOhlc;
    this.showLine = next.showLine;
    this.series.candles.applyOptions({visible: this.showOhlc});
    this.series.line.applyOptions({visible: this.showLine});
    this._syncPriceModeControls();
    this._drawMarkers();               // re-anchor markers on the visible series
    this._reselect();
  }

  setSmoothLevel(level) {
    this.smoothLevel = Math.max(0, Math.min(MAX_LEVEL, level | 0));
    this._applySmoothing();
  }

  /** Switch between the 0..10 presets and the typed {back, fwd} window. */
  setSmoothCustom(on) {
    this.smoothIsCustom = !!on;
    this._applySmoothing();
  }

  /** Custom window: `back` bars behind the current bar, `fwd` bars ahead. */
  setSmoothWindow(back, fwd) {
    this.smoothCustom = {
      back: Math.max(0, Math.min(MAX_BARS, Math.round(back) || 0)),
      fwd: Math.max(0, Math.min(MAX_BARS, Math.round(fwd) || 0)),
    };
    this._applySmoothing();
  }

  /** What the smoothing functions take: a level, or a custom window. */
  _smoothSetting() {
    return this.smoothIsCustom ? this.smoothCustom : this.smoothLevel;
  }

  _applySmoothing() {
    this._applyLineType();
    this.series.line.setData(smoothCloses(this.view.candles, this._smoothSetting()));
    this._syncSmoothControls();
  }

  setShowTrades(on) { this.showTrades = on; this._drawMarkers(); }
  setShowHoles(on) { this.showHoles = on; this._drawMarkers(); }

  /** Show or hide the equity pane; the price pane takes the freed height. */
  setShowEquity(on) {
    this.showEquity = on;
    this._applyEquityVisible();
  }

  setShowEmas(on) {
    this.series.emaFast.applyOptions({visible: on});
    this.series.emaSlow.applyOptions({visible: on});
  }

  // -- selection ---------------------------------------------------------
  /** Draw a trade's entry/SL/TP lines and zoom to it. */
  selectTrade(id) {
    const trade = store.trades.find(t => t.id === id);
    if (!trade) return;
    this.selectedId = id;
    emit(EVENTS.TRADE_SELECTED, {id});

    // remove from whichever series drew them: switching to the line chart makes
    // a different series active, and a price line can only be removed from its own
    if (this.priceLineOwner) {
      for (const line of this.priceLines) {
        try { this.priceLineOwner.removePriceLine(line); } catch { /* series gone */ }
      }
    }
    const series = this.activeSeries;
    this.priceLineOwner = series;
    this.priceLines = [
      [trade.entry_price, COLORS.line, 'entry'],
      [trade.sl, COLORS.down, 'SL'],
      [trade.tp, COLORS.up, 'TP'],
    ].map(([price, color, title]) => series.createPriceLine({
      price, color, lineWidth: 1, title, axisLabelVisible: true,
      lineStyle: LightweightCharts.LineStyle.Dashed,
    }));

    if (trade.entry_time < this.firstTime || trade.entry_time > this.lastTime) {
      toast('Trade #' + id + ' is outside the exported chart window');
      return;
    }
    // The range is set in BAR INDICES, not timestamps: the time scale is
    // index-based (it closes weekend and holiday gaps), so a timestamp range
    // does not map to the span you expect — and a 5-minute trade asked for in
    // seconds is invisible once the chart is on 1D.
    const from = barIndexAt(this.view, trade.entry_time);
    const to = Math.max(from, barIndexAt(this.view, trade.exit_time));
    const pad = Math.max(12, Math.round((to - from) * 2));
    this.charts.price.timeScale().setVisibleLogicalRange({from: from - pad, to: to + pad});
    $('#btnFit').classList.remove('on');
  }

  // -- internals ---------------------------------------------------------
  _buildView() {
    return buildView(this.timeframe, {
      candles: store.rawCandles,
      emaFast: store.candles.ema_fast || [],
      emaSlow: store.candles.ema_slow || [],
      holes: store.holes,
    });
  }

  _teardown() {
    for (const key of ['price', 'equity']) {
      if (!this.charts[key]) continue;
      try { this.charts[key].remove(); } catch { /* already gone */ }
      this.charts[key] = null;
    }
    this.sizeCompare.destroy();
    this.trend.destroy();
    this.priceLines = [];
    this.priceLineOwner = null;
    this.selectedId = null;
  }

  _pricePaneHTML() {
    const tabs = TF_ORDER.map(tf =>
      `<button data-tf="${tf}" class="${tf === this.timeframe ? 'on' : ''}">${tf}</button>`).join('');
    // legend and toolbar share one strip so they reflow past each other
    // instead of overlapping when the pane narrows
    return '<div id="tradeTip"></div><div class="pane-chrome"><div id="legend"></div>' +
      '<div class="toolbar-stack"><div class="toolbar">' +
      '<span class="cmp-seg" id="tfSeg" title="Chart timeframe — aggregated from the ' +
        'same 5m bars; trades always execute on 5m">' + tabs + '</span>' +
      '<button id="btnFit" class="on">Fit all</button>' +
      '<button id="btnAuto">Auto zoom</button>' +
      `<button id="btnOhlc" class="${this.showOhlc ? 'on' : ''}" ` +
        'title="Draw candles">OHLC</button>' +
      `<button id="btnLine" class="${this.showLine ? 'on' : ''}" ` +
        'title="Draw a smooth close-price line — can sit on top of the candles">Line</button>' +
      '<button id="btnEma" class="on">EMAs</button>' +
      '<button id="btnMarks" class="on">Markers</button>' +
      '<button id="btnCmp">Size cmp</button>' +
      `<button id="btnGaps" class="${this.showHoles ? 'on' : ''}" ` +
        'title="Mark stretches where the feed has no bars at all">Gaps</button>' +
      `<button id="btnEquity" class="${this.showEquity ? 'on' : ''}" ` +
        'title="Show the equity curve pane">Equity</button>' +
      `<button id="btnTrend" class="${this.trend.visible ? 'on' : ''}" ` +
        'title="Show the fuzzy trend pane (0 = down, 0.5 = sideways, 1 = up)">Trend</button>' +
      '</div>' +
      // its own line under the buttons: appearing here shifts nothing sideways
      '<span class="tb-smooth" id="smoothWrap">' +
        '<span id="smoothPreset" title="Line smoothness — swipe to adjust ' +
          '(0 = raw, 10 = smoothest)">' +
          `<input id="lineSmooth" type="range" min="0" max="${MAX_LEVEL}" step="1" ` +
          `value="${this.smoothLevel}"><b id="smoothVal">${this.smoothLevel}</b></span>` +
        '<span id="smoothWindow" title="Custom window: bars fitted behind and ' +
          'ahead of each bar. 0 ahead = causal, no repainting.">' +
          `back<input id="smoothBack" type="number" min="0" max="${MAX_BARS}" step="1" ` +
          `value="${this.smoothCustom.back}">` +
          `fwd<input id="smoothFwd" type="number" min="0" max="${MAX_BARS}" step="1" ` +
          `value="${this.smoothCustom.fwd}">` +
        '</span>' +
        '<button id="btnSmoothCustom" title="Type an exact window instead of ' +
          'using the preset levels">m·n</button>' +
      '</span>' +
      '</div></div>';
  }

  _createPriceSeries() {
    const chart = this.charts.price;
    this.series.candles = chart.addCandlestickSeries({
      upColor: COLORS.up, downColor: COLORS.down, borderVisible: false,
      wickUpColor: COLORS.up, wickDownColor: COLORS.down,
      visible: this.showOhlc});
    this.series.candles.priceScale().applyOptions({scaleMargins: {top: 0.08, bottom: 0.12}});
    this.series.line = chart.addLineSeries({
      color: COLORS.line, lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: true,
      lineType: LightweightCharts.LineType.Curved,
      visible: this.showLine});
    this.series.emaFast = chart.addLineSeries({color: COLORS.emaFast, lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    this.series.emaSlow = chart.addLineSeries({color: COLORS.emaSlow, lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
  }

  /* Equity is aligned to candle bars (forward-filled) so the logical-range sync
     lines up bar for bar and the curve actually renders. */
  _createEquitySeries() {
    const chart = this.charts.equity;
    chart.priceScale('right').applyOptions(
      {mode: LightweightCharts.PriceScaleMode.Logarithmic});
    this.series.equity = chart.addAreaSeries({
      lineColor: COLORS.equity, topColor: 'rgba(76,141,255,.35)',
      bottomColor: 'rgba(76,141,255,.02)', lineWidth: 2,
      priceLineVisible: false, lastValueVisible: true});
    this.series.equity.setData(this._equityData());
    this.series.equity.createPriceLine({
      price: store.stats.initial_capital, color: COLORS.neutral,
      lineStyle: LightweightCharts.LineStyle.Dashed, lineWidth: 1,
      axisLabelVisible: true, title: 'start'});
  }

  _setSeriesData() {
    const bars = this.view.candles;
    this.series.candles.setData(bars.map(
      r => ({time: r[0], open: r[1], high: r[2], low: r[3], close: r[4]})));
    this.series.line.setData(smoothCloses(bars, this._smoothSetting()));
    this.series.emaFast.setData(this.view.emaFast.map(r => ({time: r[0], value: r[1]})));
    this.series.emaSlow.setData(this.view.emaSlow.map(r => ({time: r[0], value: r[1]})));
  }

  _refreshOverlays() {
    this.tradeIndex = buildTradeIndex(this.view, store.trades);
    this._drawMarkers();
  }

  _drawMarkers() {
    const active = this.activeSeries;
    const other = active === this.series.candles ? this.series.line : this.series.candles;
    if (other) other.setMarkers([]);
    active.setMarkers(buildMarkers(this.view, {
      trades: store.trades, holes: store.holes,
      showTrades: this.showTrades, showHoles: this.showHoles}));
  }

  _applyEquityVisible() {
    $('#equity').style.display = this.showEquity ? 'block' : 'none';
    if (!this.showEquity) return;
    // the pane was zero-sized while hidden, so put it back on the shared range
    requestAnimationFrame(() => {
      const range = this.charts.price.timeScale().getVisibleLogicalRange();
      if (range) this.charts.equity.timeScale().setVisibleLogicalRange(range);
    });
  }

  /* The trend lines are always measured on 5m and 1h bars, whatever timeframe
     the price chart is currently drawn at. */
  _renderTrend() {
    this.trend.render(this.view, this.charts.price, {
      fast: store.rawCandles,
      slow: buildView('1h', {candles: store.rawCandles, holes: store.holes}).candles,
    });
  }

  /* Forward-fill realized equity onto every candle timestamp. */
  _equityData() {
    const curve = store.results.equity_curve;
    const out = [];
    let index = 0, equity = store.stats.initial_capital;
    for (const [time] of this.view.candles) {
      while (index < curve.length && curve[index][0] <= time) equity = curve[index++][1];
      out.push({time, value: equity});
    }
    return out;
  }

  _applyLineType() {
    // straight segments when the window is empty (raw closes); let the renderer
    // curve the rest a touch
    const {back, fwd} = smoothWindow(this._smoothSetting());
    this.series.line.applyOptions({lineType: back + fwd === 0
      ? LightweightCharts.LineType.Simple : LightweightCharts.LineType.Curved});
  }

  /** Mirror the smoothing state into its controls. */
  _syncSmoothControls() {
    const custom = this.smoothIsCustom;
    $('#btnSmoothCustom').classList.toggle('on', custom);
    $('#smoothPreset').hidden = custom;
    $('#smoothWindow').hidden = !custom;
    $('#lineSmooth').value = this.smoothLevel;
    $('#smoothVal').textContent = this.smoothLevel;
    $('#smoothBack').value = this.smoothCustom.back;
    $('#smoothFwd').value = this.smoothCustom.fwd;
  }

  _syncPriceModeControls() {
    $('#btnOhlc').classList.toggle('on', this.showOhlc);
    $('#btnLine').classList.toggle('on', this.showLine);
    $('#smoothWrap').classList.toggle('on', this.showLine);
    this._syncSmoothControls();
    this._applyLineType();
  }

  _setZoomButton(active) {
    for (const id of ['#btnFit', '#btnAuto']) {
      $(id) && $(id).classList.toggle('on', id === active);
    }
  }

  _reselect() {
    if (this.selectedId == null) return;
    const id = this.selectedId;
    this.selectedId = null;
    this.selectTrade(id);
  }

  _wireToolbar() {
    $$('#tfSeg button').forEach(button => {
      button.onclick = () => this.setTimeframe(button.dataset.tf);
    });
    $('#btnFit').onclick = () => this.fitAll();
    $('#btnAuto').onclick = () => this.autoZoom();
    $('#btnOhlc').onclick = () => this.setPriceSeries('ohlc', !this.showOhlc);
    $('#btnLine').onclick = () => this.setPriceSeries('line', !this.showLine);
    $('#lineSmooth').oninput = event => this.setSmoothLevel(+event.target.value);
    $('#btnSmoothCustom').onclick = () => this.setSmoothCustom(!this.smoothIsCustom);
    const onWindowInput = () =>
      this.setSmoothWindow(+$('#smoothBack').value, +$('#smoothFwd').value);
    $('#smoothBack').onchange = onWindowInput;
    $('#smoothFwd').onchange = onWindowInput;
    $('#btnEma').onclick = event =>
      this.setShowEmas(event.target.classList.toggle('on'));
    $('#btnMarks').onclick = event =>
      this.setShowTrades(event.target.classList.toggle('on'));
    $('#btnGaps').onclick = event =>
      this.setShowHoles(event.target.classList.toggle('on'));
    $('#btnEquity').onclick = event =>
      this.setShowEquity(event.target.classList.toggle('on'));
    $('#btnTrend').onclick = event => {
      this.trend.toggle(event.target.classList.toggle('on'));
      this._renderTrend();
    };
    $('#trendFast').onclick = event =>
      this.trend.setLine('fast', event.target.classList.toggle('on'));
    $('#trendSlow').onclick = event =>
      this.trend.setLine('slow', event.target.classList.toggle('on'));
    $('#trendLevel').oninput = event => {
      this.trend.setLevel(+event.target.value);
      this._renderTrend();
    };
    $('#btnTrendCustom').onclick = () => {
      this.trend.setCustom(!this.trend.isCustom);
      this._renderTrend();
    };
    const onTrendWindow = () => {
      this.trend.setWindow(+$('#trendBack').value, +$('#trendFwd').value);
      this._renderTrend();
    };
    $('#trendBack').onchange = onTrendWindow;
    $('#trendFwd').onchange = onTrendWindow;
    $('#trendGain').oninput = event => {
      this.trend.setGain(+event.target.value);
      this._renderTrend();
    };
    $('#btnCmp').onclick = event => {
      this.sizeCompare.toggle(event.target.classList.toggle('on'));
      this.sizeCompare.render(this.view, this.charts.price);
    };
    $('#cmpN').onchange = event => {
      this.sizeCompare.setLookback(+event.target.value);
      this.sizeCompare.render(this.view, this.charts.price);
    };
    $('#cmpMetricBody').onclick = () => this._setCompareMetric('body');
    $('#cmpMetricTr').onclick = () => this._setCompareMetric('tr');
  }

  _setCompareMetric(metric) {
    this.sizeCompare.setMetric(metric);
    this.sizeCompare.render(this.view, this.charts.price);
  }

  _wireCrosshair() {
    const legend = $('#legend'), tip = $('#tradeTip');
    legend.innerHTML = LEGEND_KEYS;
    this.charts.price.subscribeCrosshairMove(point => {
      // line mode interpolates x, so snap it back onto a real bar first
      const bar = point.time ? nearestBar(this.view, point.time) : null;
      if (!bar) {
        legend.innerHTML = LEGEND_KEYS;
        tip.style.display = 'none';
        return;
      }
      legend.innerHTML = legendHTML(bar.row, this.timeframe,
        {ohlc: this.showOhlc, line: this.showLine});
      this._renderTooltip(tip, bar.time, point);
    });
  }

  _renderTooltip(tip, barTime, point) {
    const hit = this.tradeIndex.get(barTime);
    if (!this.showTrades || !hit || !point.point) {
      tip.style.display = 'none';
      return;
    }
    const trade = hit.entries[0] || hit.exits[0];
    tip.innerHTML = tradeTooltipHTML(trade, hit.entries.length + hit.exits.length - 1);
    tip.style.display = 'block';
    // position near the cursor, clamped inside the price pane
    const pane = $('#price');
    let x = point.point.x + 16, y = point.point.y + 16;
    if (x + tip.offsetWidth > pane.clientWidth - 8) x = point.point.x - tip.offsetWidth - 16;
    if (y + tip.offsetHeight > pane.clientHeight - 8) {
      y = Math.max(8, pane.clientHeight - tip.offsetHeight - 8);
    }
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
}
