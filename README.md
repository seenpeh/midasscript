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
| `docs/` | Persian architecture document (`ARCHITECTURE.fa.md`) + print-ready HTML build |
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

### Architecture document

A full architectural review and technical reference (in Persian, with English
terms alongside) lives in [`docs/ARCHITECTURE.fa.md`](docs/ARCHITECTURE.fa.md).
To produce a print-ready RTL page you can save as PDF:

```bash
./docs/build-pdf.sh
```

That renders the Markdown through pandoc with `docs/_pdf-style.html`; open the
resulting `docs/ARCHITECTURE.fa.html` in a browser and print to PDF. The
Markdown stays the single source of truth — the HTML is generated, never edited.

## Data

`data.csv` is tracked in the repo (semicolon-separated
`Date;Open;High;Low;Close;Volume`, dates like `2004.06.11 07:15`). To
regenerate the derived JSONs from it (or after swapping in your own CSV, e.g.
`~/XAU_5m_data.csv`), run:

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

## Trend labelling (this branch)

A second, separate page for hand-labelling trends — the training set for the
supervised model. It is only the chart: candles, times, timeframes and
rectangles. No EMAs, no trades, no backtest, no optimiser.

```bash
python3 label_serve.py   # http://localhost:8766/
```

Pick a trend (**Uptrend** green, **Sideway** yellow, **Downtrend** red), click
the first candle of the move and then the last one. The rectangle's top and
bottom snap to the highest high and lowest low of that range, so its height is
measured, never dragged. Click a rectangle to select it and press Delete (or
the Delete button) to remove it; Esc cancels a half-drawn one.

Labelling happens on **1h** and **4h** only. Each is labelled independently —
a label belongs to the timeframe it was drawn on, and the same candles may be
an uptrend on 1h and a sideway on 4h. Labels on one timeframe may not overlap each other; the server refuses it,
because one candle cannot be two trends. Gaps are fine: an unlabelled candle
is simply not training data.

**The daily homework** is the bar under the header: 800 candles on 1h and 200
on 4h. It counts candles labelled since midnight, in your own local time, and
the page opens where the last label on that timeframe ended — the **Resume**
button jumps back there at any time.

Labels live in `labels.db` (sqlite, one row per rectangle: timeframe, first
and last candle time, candle count, trend, when it was drawn). The file is
**committed to git**, so the day's work travels like code:

```bash
git pull                        # start of the day: get the latest labels
python3 label_serve.py          # label at http://localhost:8766/
git add labels.db && git commit -m "Labels for <date>" && git push
```

Git cannot merge a binary file, so only one person labels at a time — two
people pushing labels from the same starting point means one of them has to
throw their day away. Export them with:

```bash
sqlite3 labels.db -header -csv "select * from labels" > labels.csv
```

## Notes

Position sizing is geometric and pyramided, so results are path-dependent and
ruin-prone at default parameters. Optimization scores MAR (`CAGR/(MaxDD+5)`)
under a hard max-drawdown cap; raw-profit objectives select blow-up configs.
Walk-forward results (OOS profit factor ~1.0–1.1) suggest a thin edge — treat
out-of-sample numbers as reality, not the full-window fit.
