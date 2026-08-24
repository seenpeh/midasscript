/* The loaded dataset, and the run settings the UI remembers between runs.

   One object owns both, so a module that needs the current results asks the
   store instead of reaching for a global that some other module happens to
   have assigned. */

import {fetchDataset} from './api.js';

export const store = {
  candles: null,        // 5m_candles_chart.json
  results: null,        // results.json
  defaultParams: null,  // strategy defaults from /api/defaults

  // what the last run was asked for — the drawer reopens showing these
  lastRun: {capital: 10000, chartDays: 730, start: '', end: ''},

  get trades() { return (this.results && this.results.trades) || []; },
  get stats() { return this.results && this.results.stats; },
  get meta() { return this.results && this.results.meta; },
  get holes() { return (this.candles && this.candles.holes) || []; },
  get rawCandles() { return (this.candles && this.candles.candles) || []; },

  setDataset({candles, results}) {
    this.candles = candles;
    this.results = results;
  },

  async reload({bust = false} = {}) {
    this.setDataset(await fetchDataset({bust}));
  },
};
