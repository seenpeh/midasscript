"""Terminal rendering: the live trade log and the end-of-run summary.

This is the only place in a backtest that prints. The engine emits events (see
`midas.engine.observer`); `ConsoleObserver` decides what a human sees, which is
why "quiet" and "print every Nth trade" are settings here rather than arguments
threaded through the engine.
"""

from __future__ import annotations

from ..engine.position import ExitReason
from ..signals.triggers import REASON_NAMES
from ..util.timeutil import format_minute
from .ansi import Palette

SUMMARY_RULE = "─" * 54

EXIT_TAGS = {
    ExitReason.STOP_LOSS: ("SL", "red"),
    ExitReason.TAKE_PROFIT: ("TP", "green"),
    ExitReason.TREND_CHANGE: ("TREND", "yellow"),
    ExitReason.TIME_EXIT: ("TIME", "yellow"),
    ExitReason.END_OF_DATA: ("EOD", "grey"),
    ExitReason.DATA_GAP: ("GAP", "yellow"),
}


class ConsoleObserver:
    """Renders engine events to stdout.

    `quiet` hides the per-trade and per-year lines but keeps the framing;
    `print_every` prints one of every N trades. Set `framing=False` to suppress
    even the framing (the optimizer uses `NullObserver` instead and pays nothing).
    """

    def __init__(self, print_every: int = 1, quiet: bool = False,
                 framing: bool = True, palette: Palette | None = None):
        self.print_every = max(1, int(print_every))
        self.quiet = bool(quiet)
        self.framing = bool(framing)
        self.paint = palette or Palette()
        self._exits_seen = 0

    # -- framing -----------------------------------------------------------
    def _frame(self, text=""):
        if self.framing:
            print(text, flush=True)

    def signals_started(self):
        self._frame("Computing signals ...")

    def signals_ready(self, entry_count, seconds):
        self._frame(f"  signals ready in {seconds:.1f}s "
                    f"({entry_count:,} raw entry signals)")

    def window_selected(self, first, last, start_ts, end_ts):
        self._frame(f"  trading window: bar {first:,} -> {last-1:,}  "
                    f"({format_minute(start_ts)} -> {format_minute(end_ts)})")

    def gap_policy(self, hole_count, warmup_bars):
        self._frame(f"  data holes: {hole_count} — positions are flattened before "
                    f"each, entries blocked for {warmup_bars} bars after")

    def run_started(self, capital, bars):
        self._frame(self.paint.bold(
            f"\n=== Backtest start  |  capital {capital:,.2f}  |  {bars:,} bars ===\n"))

    def run_finished(self, seconds, trades, equity):
        self._frame(self.paint.bold(
            f"\n=== Backtest done in {seconds:.1f}s  |  {trades:,} trades  |  "
            f"final equity {equity:,.2f} ===\n"))

    def account_ruined(self, timestamp, trades, equity, floor_fraction):
        self._frame(self.paint.bold(self.paint.red(
            f"\n!!! ACCOUNT EFFECTIVELY RUINED at {format_minute(timestamp)} after "
            f"{trades:,} trades (equity {equity:,.2f} <= "
            f"{floor_fraction*100:.0f}% of start). Halting. !!!\n")))

    # -- the live log ------------------------------------------------------
    def year_started(self, timestamp, open_positions, closed_trades, equity):
        if self.quiet:
            return
        print(self.paint.bold(self.paint.grey(
            f"--- {format_minute(timestamp)[:4]}  |  open {open_positions}  "
            f"closed {closed_trades:,}  equity {equity:,.2f} ---")), flush=True)

    def position_opened(self, position):
        # `position.id + 1` keeps the historical cadence: the counter used to be
        # incremented before the line was printed.
        if self.quiet or (position.id + 1) % self.print_every:
            return
        print(self.format_entry(position), flush=True)

    def position_closed(self, trade):
        if self.quiet:
            return
        self._exits_seen += 1
        if self._exits_seen % self.print_every == 0:
            print(self.format_exit(trade), flush=True)

    # -- line formatting ---------------------------------------------------
    def format_entry(self, position) -> str:
        arrow = "▲ LONG " if position.is_long else "▼ SHORT"
        colour = self.paint.green if position.is_long else self.paint.red
        return (f"{self.paint.grey(format_minute(position.entry_time))}  {colour(arrow)} "
                f"entry @ {position.entry_price:.2f}  qty {position.quantity:.4f}  "
                f"SL {position.stop_loss:.2f}  TP {position.take_profit:.2f}  "
                f"{self.paint.cyan(REASON_NAMES[position.reason])} "
                f"RR 1:{position.risk_reward:.1f}  risk {position.risk_pct:.1f}%")

    def format_exit(self, trade) -> str:
        label, style = EXIT_TAGS[trade.exit_reason]
        pnl = (self.paint.green(f"+{trade.pnl:,.2f}") if trade.pnl >= 0
               else self.paint.red(f"{trade.pnl:,.2f}"))
        return (f"{self.paint.grey(format_minute(trade.exit_time))}    "
                f"✖ exit {trade.position.side.upper()} @ {trade.exit_price:.2f}  "
                f"{self.paint.paint(style, label)}  PnL {pnl}  "
                f"eq={trade.equity_after:,.2f}")


# ---------------------------------------------------------------------------
# End-of-run summary
# ---------------------------------------------------------------------------
SUMMARY_ROWS = (
    ("Initial capital", lambda s: f"{s['initial_capital']:,.2f}"),
    ("Final equity", lambda s: f"{s['final_equity']:,.2f}"),
    ("Net profit", lambda s: f"{s['net_profit']:,.2f}  ({s['return_pct']:+.2f}%)"),
    ("CAGR", lambda s: f"{s['cagr_pct']:+.2f}%"),
    ("Total trades", lambda s: f"{s['total_trades']:,}"),
    ("Win rate", lambda s: f"{s['win_rate']:.2f}%  ({s['wins']:,}W / {s['losses']:,}L)"),
    ("Profit factor", lambda s: f"{s['profit_factor']}"),
    ("Avg win / loss", lambda s: f"{s['avg_win']:,.2f} / {s['avg_loss']:,.2f}"),
    ("Expectancy/trade", lambda s: f"{s['expectancy']:,.2f}"),
    ("Largest win/loss", lambda s: f"{s['largest_win']:,.2f} / {s['largest_loss']:,.2f}"),
    ("Max drawdown", lambda s: f"{s['max_drawdown']:,.2f}  ({s['max_drawdown_pct']:.2f}%)"),
    ("Max consec W/L", lambda s: f"{s['max_consec_wins']} / {s['max_consec_losses']}"),
    ("Long / Short", lambda s: f"{s['long_trades']:,} ({s['long_win_rate']}%) / "
                               f"{s['short_trades']:,} ({s['short_win_rate']}%)"),
    ("Avg bars held", lambda s: f"{s['avg_bars_held']}"),
)


def print_summary(stats, palette: Palette | None = None) -> None:
    paint = palette or Palette()
    if stats.get("total_trades", 0) == 0:
        print(paint.yellow("No trades were generated."))
        return
    print(paint.bold("\n" + SUMMARY_RULE))
    print(paint.bold("  BACKTEST SUMMARY"))
    print(SUMMARY_RULE)
    for label, render in SUMMARY_ROWS:
        print(f"  {label:<18} {paint.bold(render(stats))}")
    print("  " + paint.grey("by trigger:"))
    for name, group in stats["by_trigger"].items():
        print(f"    {name:<28} {group['trades']:>6,} trades  "
              f"WR {group['win_rate']:>5.1f}%  net {group['net_pnl']:>12,.2f}")
    print("  " + paint.grey("by exit:"))
    for name, group in stats["by_exit"].items():
        print(f"    {name:<28} {group['count']:>6,}  net {group['net_pnl']:>12,.2f}")
    print(SUMMARY_RULE + "\n")


# ---------------------------------------------------------------------------
# Data-integrity report (see midas.data.timeframes.integrity_report)
# ---------------------------------------------------------------------------
INTEGRITY_COUNTS = ("duplicate_timestamps", "out_of_order", "off_grid",
                    "ohlc_violations", "nonpositive_prices")


def print_integrity_report(report: dict) -> None:
    print(f"  bars                 {report['bars']:,}  "
          f"({report['from']} -> {report['to']})")
    for key in INTEGRITY_COUNTS:
        count = report[key]
        print(f"  {key:<20} {count:,}" + ("" if count == 0 else "   <-- PROBLEM"))
    print(f"  market closures      {report['closures']:,}  "
          f"(weekends / holidays — expected)")
    if not report["holes"]:
        print("  data holes           0")
        return
    print(f"  DATA HOLES           {len(report['holes'])}  (missing bars — trading "
          f"is suspended across these)")
    for hole in report["holes"]:
        print(f"      {hole['from']}  ->  {hole['to']}   {hole['days']} days")
