# UltScript

Python port, backtester, and walk-forward optimizer for the "Ultimate script v0.3.7" Pine strategy, with a browser chart viewer.

## Files

| File | Purpose |
| --- | --- |
| `UltScript.pine` | Original Pine Script strategy |
| `strategy.py` | Vectorized Python port of the signal logic |
| `backtest.py` | Event-driven backtest engine + CLI |
| `optimize.py` | Walk-forward optimization (Optuna) |
| `serve.py` | Static server + `/api/run`, `/api/optimize/*` |
| `index.html` | TradingView-style viewer (lightweight-charts) |
| `convert_csv.py` | `data.csv` → compact `5m_candles.json` |

## Data

Not tracked (too large). Supply `data.csv` as semicolon-separated
`Date;Open;High;Low;Close;Volume` with dates like `2004.06.11 07:15`, then run:

```bash
python3 convert_csv.py
```

## Usage

```bash
python3 serve.py   # http://localhost:8765/
```

```bash
python3 backtest.py --quiet
```

```bash
python3 optimize.py --groups risk_exposure rr signal
```

## Notes

Position sizing is geometric and pyramided, so results are path-dependent and
ruin-prone at default parameters. Optimization scores MAR (`CAGR/(MaxDD+5)`)
under a hard max-drawdown cap; raw-profit objectives select blow-up configs.
Walk-forward results (OOS profit factor ~1.0–1.1) suggest a thin edge — treat
out-of-sample numbers as reality, not the full-window fit.
