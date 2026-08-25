#!/usr/bin/env python3
"""Entry point: `python3 backtest.py [options]`.

The backtester itself lives in the `midas` package — see `midas/engine/` for the
run loop and `midas/cli/backtest_cli.py` for the flags this script accepts.
"""

from midas.cli.backtest_cli import main

if __name__ == "__main__":
    main()
