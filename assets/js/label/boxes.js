/* The labelled rectangles, painted behind the candles.

   lightweight-charts has no rectangle tool, so this is a series primitive —
   the same mechanism `assets/js/trend/ctdOverlay.js` uses to shade its zones:
   attach it to the candle series, hand it the labels once per view, and it
   draws into the pane's own canvas on every zoom and pan.

   A rectangle's height is never stored or chosen: it is the highest high and
   the lowest low of the candles it covers, measured here, so it always hugs
   the range it labels at whatever timeframe is drawn.

   It also owns hit-testing (`at`), because it is the only thing that knows
   where the boxes ended up. */

import {barIndexAt} from '../chart/timeframes.js';

export const TRENDS = ['up', 'side', 'down'];
export const TREND_COLORS = {
  up:   {fill: 'rgba(46,189,133,0.15)', edge: 'rgba(46,189,133,0.95)'},
  side: {fill: 'rgba(240,160,32,0.15)', edge: 'rgba(240,160,32,0.95)'},
  down: {fill: 'rgba(224,83,61,0.15)',  edge: 'rgba(224,83,61,0.95)'},
};
const PENDING_DASH = [6, 4];

export class LabelBoxes {
  constructor() {
    this.view = {tf: '5m', sec: 300, candles: []};
    this.boxes = [];         // {id, trend, i0, i1, top, bottom}
    this.pending = null;     // {trend, i0, i1, top, bottom} while drawing
    this.selectedId = null;
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
    const renderer = {draw: () => {}, drawBackground: target => this._draw(target)};
    this._views = [{renderer: () => renderer, zOrder: () => 'bottom'}];
  }

  // -- primitive interface -----------------------------------------------
  attached({chart, series, requestUpdate}) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
  }

  detached() { this._chart = this._series = this._requestUpdate = null; }

  paneViews() { return this._views; }

  updateAllViews() {}

  // -- state -------------------------------------------------------------
  /** Map every label of this view's timeframe onto its bars. Labels whose
      candles are not in the file (a shorter dataset) are simply not drawn. */
  setData(view, labels) {
    this.view = view;
    this.boxes = [];
    for (const label of labels) {
      if (label.tf !== view.tf) continue;
      const i0 = barIndexAt(view, label.start_ts);
      const i1 = barIndexAt(view, label.end_ts);
      if (i0 < 0 || i1 < 0) continue;
      this.boxes.push({id: label.id, trend: label.trend, i0, i1,
                       ...extent(view, i0, i1)});
    }
    this._redraw();
  }

  /** The rectangle being drawn right now, or null once it is placed. */
  setPending(trend, i0, i1) {
    this.pending = trend == null ? null
      : {trend, i0, i1, ...extent(this.view, i0, i1)};
    this._redraw();
  }

  select(id) {
    this.selectedId = id;
    this._redraw();
  }

  /** The box drawn over bar `index`, or null. Boxes cannot overlap (the store
      refuses it), so at most one can match. */
  at(index) {
    return this.boxes.find(box => index >= box.i0 && index <= box.i1) || null;
  }

  get selected() {
    return this.boxes.find(box => box.id === this.selectedId) || null;
  }

  _redraw() { if (this._requestUpdate) this._requestUpdate(); }

  // -- drawing -----------------------------------------------------------
  _draw(target) {
    if (!this._chart || !this._series) return;
    const timeScale = this._chart.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    if (!range) return;
    const x0 = timeScale.logicalToCoordinate(0), x1 = timeScale.logicalToCoordinate(1);
    if (x0 == null || x1 == null) return;
    const half = Math.max(0.5, (x1 - x0) / 2);
    const from = Math.floor(range.from) - 1, to = Math.ceil(range.to) + 1;

    target.useBitmapCoordinateSpace(({context: ctx, horizontalPixelRatio: hr,
                                      verticalPixelRatio: vr}) => {
      const left = i => (timeScale.logicalToCoordinate(i) - half) * hr;
      const right = i => (timeScale.logicalToCoordinate(i) + half) * hr;
      for (const box of this.boxes) {
        if (box.i1 < from || box.i0 > to) continue;
        this._rect(ctx, box, left(box.i0), right(box.i1), hr, vr,
                   box.id === this.selectedId ? 3 : 1);
      }
      if (this.pending) {
        this._rect(ctx, this.pending, left(this.pending.i0), right(this.pending.i1),
                   hr, vr, 2, PENDING_DASH);
      }
    });
  }

  _rect(ctx, box, xa, xb, hr, vr, edgePx, dash = null) {
    const yTop = this._series.priceToCoordinate(box.top);
    const yBottom = this._series.priceToCoordinate(box.bottom);
    if (yTop == null || yBottom == null) return;
    const colors = TREND_COLORS[box.trend];
    const a = Math.floor(xa), b = Math.ceil(xb);
    const top = Math.round(yTop * vr), bottom = Math.round(yBottom * vr);
    ctx.fillStyle = colors.fill;
    ctx.fillRect(a, top, b - a, Math.max(1, bottom - top));
    ctx.strokeStyle = colors.edge;
    ctx.lineWidth = Math.max(1, Math.round(edgePx * hr));
    ctx.setLineDash(dash ? dash.map(d => d * hr) : []);
    ctx.strokeRect(a, top, b - a, Math.max(1, bottom - top));
    ctx.setLineDash([]);
  }
}

/** Highest high and lowest low over bars i0..i1 of `view` — the rectangle's
    top and bottom, which is why neither is ever stored. */
export function extent(view, i0, i1) {
  const bars = view.candles;
  let top = bars[i0][2], bottom = bars[i0][3];
  for (let i = i0 + 1; i <= i1; i++) {
    if (bars[i][2] > top) top = bars[i][2];
    if (bars[i][3] < bottom) bottom = bars[i][3];
  }
  return {top, bottom};
}
