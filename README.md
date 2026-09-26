# MidasScript

A research toolkit for a rule-based intraday trading strategy on spot gold (XAU/USD). It
takes a strategy written in TradingView's Pine Script, ports it to Python, and adds what
Pine Script can't do: a reproducible backtester, walk-forward optimization, and an
interactive chart for inspecting every trade. It is the research engine behind
[BazarPeech](https://bazarpeech.com).

## What it does

- **Python port of the strategy.** An EMA trend-regime filter and three "big candle" entry
  triggers (single oversized candle, same-direction run, reversal), with pyramided position
  sizing, stops and targets.
- **Event-driven backtester.** Runs on about 20 years of 5-minute bars. It models broker
  fills, positions and account equity, and reports CAGR, maximum drawdown, win rate,
  profit factor, monthly returns and annualized Sharpe/Sortino ratios.
- **Data-quality handling.** CSV import sorts and de-duplicates bars, rejects impossible
  OHLC values, and tells normal market closures apart from missing-data holes. The engine
  closes positions before a hole instead of trading through data that doesn't exist.
  Higher-timeframe candles never span a hole.
- **Walk-forward optimizer.** Bayesian (TPE) parameter search with Optuna across rolling
  in-sample and out-of-sample folds. It scores a MAR-style objective under a hard
  maximum-drawdown cap and reports walk-forward efficiency to guard against overfitting.
- **Interactive viewer.** A browser chart built on TradingView's lightweight-charts. It
  offers 5m to 1D timeframes resampled on the fly, trade markers, statistics and monthly
  return panels, an ATR-normalized "fuzzy" trend indicator, and runs of backtests and
  optimizations from the UI.

## Engineering

- A layered `midas` package (data → signals → engine → reporting → optimizer → server)
  where each layer depends only on the layers below it. The engine reports to an observer
  instead of printing, and nothing below the server knows about HTTP.
- New entry rules plug in as classes without touching the backtester.
- Unit tests for the trading rules (`python3 -m unittest discover tests`).
- An architecture document in Persian: [`docs/ARCHITECTURE.fa.md`](docs/ARCHITECTURE.fa.md).

**Stack:** Python, NumPy, Optuna, vanilla JavaScript, lightweight-charts, Pine Script.

## Run it

```bash
python3 convert_csv.py   # import 5-minute XAU/USD bars (data not included)
python3 backtest.py
python3 serve.py         # viewer at http://localhost:8765/
```

See [`docs/USAGE.md`](docs/USAGE.md) for data format, command-line options and the
optimizer.

> Walk-forward tests show only a thin out-of-sample edge. This is a research project,
> not investment advice.
