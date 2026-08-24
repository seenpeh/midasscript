"""The "run one backtest and write its artefacts" use case.

The CLI and the HTTP server both want exactly this sequence and nothing more,
so it lives in one place instead of being duplicated on either side of the
transport boundary. It is the seam between the pure engine and the outside
world: everything above it prints and writes files, everything below it does not.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.backtester import Backtester, ExecutionSettings
from ..engine.statistics import statistics_for
from ..reporting import writers
from ..reporting.console import ConsoleObserver, print_summary


@dataclass(frozen=True)
class OutputSettings:
    """Where the run's artefacts go, and how much of the chart to export."""
    results_path: str = "results.json"
    chart_path: str = "5m_candles_chart.json"
    chart_days: float = 730.0
    write_files: bool = True


def run_backtest(series, params, execution: ExecutionSettings,
                 outputs: OutputSettings | None = None,
                 observer=None, announce=print) -> dict:
    """Run, summarise, and write `results.json` + the chart slice. Returns stats."""
    outputs = outputs or OutputSettings()
    observer = observer if observer is not None else ConsoleObserver()

    result = Backtester(params, execution, observer).run(series)
    stats = statistics_for(result, series.epoch)
    if result.ruin:
        stats["ruined"] = True
        stats["ruin_date"] = result.ruin.date
    print_summary(stats)

    if outputs.write_files:
        announce("Writing outputs ...")
        announce(str(writers.write_results(outputs.results_path, result, stats,
                                           params, series)))
        # The EMAs the chart draws are the ones the run actually traded on.
        announce(str(writers.write_chart_slice(
            outputs.chart_path, series, result.trades, outputs.chart_days,
            result.signals.ema_fast, result.signals.ema_slow)))
    return stats
