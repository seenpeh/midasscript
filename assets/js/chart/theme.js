/* Chart colours and the options every chart pane shares.

   These mirror the custom properties in assets/css/app.css; the chart library
   cannot read CSS variables, so this is the one place its colours are set. */

export const COLORS = {
  up: '#2ebd85', down: '#e0533d', line: '#cfd6df',
  // one per smoothing filter, so overlaid lines stay tellable apart
  filterSg: '#cfd6df', filterSma: '#f6c453', filterEma: '#7dd3fc',
  emaFast: '#3b82f6', emaSlow: '#f0a020',
  equity: '#4c8dff', neutral: '#5a6472', dim: '#39414d', mid: '#6b8cae',
  trendFast: '#c084fc', trendSlow: '#22d3ee',
  hole: '#f0a020',
};

/** Mouse wheel zooms centred on the cursor and does NOT pan. */
export function baseChartOptions() {
  return {
    layout: {background: {color: '#0e1116'}, textColor: '#9aa4b2', fontSize: 11},
    grid: {vertLines: {color: '#1a1f27'}, horzLines: {color: '#1a1f27'}},
    // a fixed axis width on every pane keeps their plot areas — and so their
    // time columns — lined up vertically, whatever each pane's labels read
    rightPriceScale: {borderColor: '#262d38', minimumWidth: 76},
    timeScale: {borderColor: '#262d38', timeVisible: true, secondsVisible: false,
      rightOffset: 6, minBarSpacing: 0.0005},
    crosshair: {mode: LightweightCharts.CrosshairMode.Normal},
    handleScroll: {mouseWheel: false, pressedMouseMove: true,
      horzTouchDrag: true, vertTouchDrag: false},
    handleScale: {mouseWheel: true, pinch: true,
      axisPressedMouseMove: true, axisDoubleClickReset: true},
    kineticScroll: {mouse: false, touch: true},
  };
}

/** Keep two charts' time axes in step (a shared lock stops the feedback loop). */
export function linkTimeScales(a, b) {
  let syncing = false;
  const first = a.timeScale(), second = b.timeScale();
  const link = (from, to) => from.subscribeVisibleLogicalRangeChange(range => {
    if (syncing || !range) return;
    syncing = true;
    to.setVisibleLogicalRange(range);
    syncing = false;
  });
  link(first, second);
  link(second, first);
}
