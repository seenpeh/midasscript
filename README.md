# MidasScript

Python port, backtester, and walk-forward optimizer for a Pine Script trading
strategy ("Ultimate script v0.3.7"), with a browser chart viewer.

## Project layout

Entry points at the root stay exactly as they were — `python3 backtest.py`,
`optimize.py`, `serve.py`, `convert_csv.py`, `timeframes.py` — but each is now a
few lines that call into the `midas` package. Every layer depends only on the
ones above it, so you can read (or replace) one without the rest.

| Path | Purpose |
| --- | --- |
| `midas/util/` | timestamps, point-series thinning — no project knowledge |
| `midas/config/params.py` | the `Params` dataclass and the one place untrusted input is coerced into it |
| `midas/data/` | the time axis: `CandleSeries`, gap detection + resampling, CSV import |
| `midas/signals/` | price → entry signals: indicators, the three triggers, the generator |
| `midas/engine/` | signals + money → trades: positions, broker fills, gaps, the run loop, statistics |
| `midas/reporting/` | trades/stats → terminal output (`ConsoleObserver`) and JSON artefacts |
| `midas/optimizer/` | search space, objective, walk-forward folds |
| `midas/server/` | HTTP transport: routing, static files, background jobs |
| `midas/app/` | the use cases both the CLI and the server call |
| `midas/cli/` | argument parsing for each entry point |
| `assets/js/`, `assets/css/` | the viewer, split the same way (data / chart / panels) |
| `tests/` | unit tests for the rules — no data file required |
| `MidasScript.pine` | original Pine Script strategy |
| `index.html` | viewer markup (lightweight-charts) |
| `bin/midas` | `midas` terminal command — starts the server and opens the viewer |

Two rules hold the shape together: **nothing below `midas/reporting/` prints**
(the engine reports events to an observer, so the optimizer runs silently and
for free), and **nothing below `midas/server/` knows an HTTP request exists**.

### Tests

```bash
python3 -m unittest discover tests
```

## Data

Not tracked (too large). Supply `data.csv` (or `~/XAU_5m_data.csv`) as
semicolon-separated `Date;Open;High;Low;Close;Volume` with dates like
`2004.06.11 07:15`, then run:

```bash
python3 convert_csv.py
```

Conversion sorts by time, drops duplicate timestamps (keeping the latest),
drops bars with impossible OHLC (non-positive prices, `high < low`, etc.), and
prints an integrity report. It also classifies every gap in the feed as either
a normal market closure (weekend/holiday, harmless) or a **data hole** — a
stretch longer than 96h where bars are simply missing — and writes the holes
into `5m_candles.json` under `"holes"`. Re-check any existing file without
reconverting:

```bash
python3 timeframes.py --data 5m_candles.json --tf 1h
```

### Why this matters for backtesting

A raw vendor feed is not one continuous 5-minute grid — the XAU_5m file used
here has two multi-day data holes (32 days in Sep–Oct 2025, 9 days in Jan
2026, plus two ~4.5-day holes in 2005/2006). Before this fix, the backtester
would happily "hold" a position across a hole and its stop-loss/take-profit
logic would fire on the reopening bar as if the intervening 32 days of price
action had simply not existed — turning a 14.7% overnight-equivalent jump into
a single unrealistic fill. Two changes fix this:

1. **The engine flattens every open position at the close of the last bar
   before a hole** (exit reason `DataGap`) and blocks new entries for
   `--gap-warmup` bars after one, instead of carrying positions through a void
   the feed never recorded. Disable with `--no-gap-flat` to reproduce the old
   behaviour.
2. **Resampling to a higher timeframe never lets a bucket span a hole.** The
   first bar after a hole always opens a fresh 15m/1h/4h/1D candle, so (say)
   the daily chart can't merge 2025-09-12 with 2025-10-15 into one bar with a
   $537 range.

The chart marks each hole with an orange "no data" marker on every timeframe
(toggle with the **Gaps** button) so you can see exactly where the feed — and
therefore the backtest — goes quiet.

## Usage

The quickest way in — from any directory, `midas` starts the server and opens
the chart in your browser:

```bash
midas
```

The terminal stays attached and streams the server log (that is where
`/api/run` and `/api/optimize` progress appears); press Ctrl-C to stop. If a
server is already listening on the port, `midas` just opens the browser at it
instead of starting a second one. Options: `--port N`, `--no-open`, `--help`;
anything else is passed straight through to `serve.py`.

**Install it** (one time — `~/.local/bin` is already on `PATH`):

```bash
ln -sfn "$PWD/bin/midas" ~/.local/bin/midas
```

It's a symlink, so edits to `bin/midas` in the repo take effect immediately.
Or run the server directly:

```bash
python3 serve.py   # http://localhost:8765/
```

```bash
python3 backtest.py --quiet
```

```bash
python3 optimize.py --groups risk_exposure rr signal
```

## Multi-timeframe chart

The viewer always trades and stores results on the underlying **5-minute**
bars — that never changes. What you *look at* is a separate choice: the
**5m / 15m / 1h / 4h / 1D** segmented control in the chart toolbar
re-aggregates the same 5m candles in the browser (open of the first bar, max
high, min low, close of the last bar, summed volume) and redraws instantly, no
server round-trip. EMAs are resampled the same way (sampled at each
higher-timeframe bar's close), and trade markers/tooltips group same-bucket
fills so a 1D candle with 30 trades inside it shows one arrow labelled `×30`
instead of 30 overlapping ones. Selecting a trade snaps the view to whichever
timeframe is active. See "Why this matters for backtesting" above for how
data holes are handled during resampling.

## Notes

Position sizing is geometric and pyramided, so results are path-dependent and
ruin-prone at default parameters. Optimization scores MAR (`CAGR/(MaxDD+5)`)
under a hard max-drawdown cap; raw-profit objectives select blow-up configs.
Walk-forward results (OOS profit factor ~1.0–1.1) suggest a thin edge — treat
out-of-sample numbers as reality, not the full-window fit.
