"""MidasScript — backtesting toolkit for the "Ultimate script" trading strategy.

Layers (each depends only on the ones above it):

    midas.util        pure helpers with no project knowledge
    midas.data        the time axis: candles, timeframes, CSV import
    midas.signals     price -> entry/exit signals (no money, no state)
    midas.engine      signals + money -> trades, equity, statistics
    midas.reporting   trades/statistics -> terminal output and JSON files
    midas.optimizer   repeated engine runs -> tuned parameters
    midas.server      HTTP transport for the browser viewer
    midas.cli         argument parsing and process entry points

Nothing below `midas.reporting` prints. Nothing below `midas.server` knows an
HTTP request exists.
"""
