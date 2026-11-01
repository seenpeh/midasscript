/* Drawing a rectangle: pick the trend, click the first candle, click the last.

   Between the two clicks the rectangle follows the crosshair, so the range —
   and the candle count it is worth towards today's homework — is visible
   before it is committed.

   Clicking inside a rectangle that is already there selects it instead of
   starting a new one: labels may not overlap, so a click there could never
   have begun a valid rectangle anyway. Esc cancels, Delete removes the
   selected one. */

import {barIndexAt} from '../chart/timeframes.js';

export class RectangleTool {
  /** `onAdd({trend, i0, i1})` stores a finished rectangle, `onDelete(box)`
      removes one, `onPending(bars|null)` reports the live candle count. */
  constructor({chart, boxes, onAdd, onDelete, onPending}) {
    this.boxes = boxes;
    this.trend = 'up';
    this.startIndex = null;
    this.onAdd = onAdd;
    this.onDelete = onDelete;
    this.onPending = onPending || (() => {});
    chart.subscribeClick(param => this._click(param));
    chart.subscribeCrosshairMove(param => this._move(param));
    document.addEventListener('keydown', event => this._key(event));
  }

  setTrend(trend) {
    this.trend = trend;
    if (this.startIndex != null) this._preview(this.startIndex);   // recolour
  }

  /** Drop a half-drawn rectangle and the selection. */
  cancel() {
    this.startIndex = null;
    this.boxes.setPending(null);
    this.boxes.select(null);
    this.onPending(null);
  }

  // -- events ------------------------------------------------------------
  _click(param) {
    const index = this._indexAt(param);
    if (index == null) return;
    if (this.startIndex == null) {
      const hit = this.boxes.at(index);
      if (hit) { this.boxes.select(hit.id); return; }
      this.boxes.select(null);
      this.startIndex = index;
      this._preview(index);
      return;
    }
    const i0 = Math.min(this.startIndex, index);
    const i1 = Math.max(this.startIndex, index);
    const trend = this.trend;
    this.cancel();
    this.onAdd({trend, i0, i1});
  }

  _move(param) {
    if (this.startIndex == null) return;
    const index = this._indexAt(param);
    if (index != null) this._preview(index);
  }

  _key(event) {
    if (event.key === 'Escape') return this.cancel();
    if (event.key !== 'Delete' && event.key !== 'Backspace') return;
    const box = this.boxes.selected;
    if (box) { event.preventDefault(); this.onDelete(box); }
  }

  _preview(index) {
    const i0 = Math.min(this.startIndex, index);
    const i1 = Math.max(this.startIndex, index);
    this.boxes.setPending(this.trend, i0, i1);
    this.onPending(i1 - i0 + 1);
  }

  /** Which drawn bar the pointer is on — null when it is off the candles. */
  _indexAt(param) {
    if (param.time == null) return null;
    const index = barIndexAt(this.boxes.view, param.time);
    return index < 0 ? null : index;
  }
}
