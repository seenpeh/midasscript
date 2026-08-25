"""Unit tests for the pieces the refactor made testable in isolation.

Run them with:

    python3 -m unittest discover tests

None of these need `5m_candles.json` or any other data file — that is the point:
the rules (fills, gaps, sizing, scoring, aggregation) are now separable from the
million-bar series they are usually applied to.
"""

import unittest

import numpy as np

from midas.config.params import ParamError, Params
from midas.data import timeframes as tf
from midas.data.series import CandleSeries, DataError
from midas.engine.account import Account, DailyLossLimit
from midas.engine.broker import Bar, IntrabarBroker, SpreadModel
from midas.engine.gaps import GapPolicy
from midas.engine.position import ExitReason, Position
from midas.engine.statistics import compute_statistics
from midas.optimizer.objective import Objective
from midas.optimizer.space import build_params
from midas.optimizer.walkforward import make_folds
from midas.util.sampling import downsample
from midas.util.timeutil import parse_timestamp


def a_position(direction=1, entry=100.0, stop=99.0, target=102.0, quantity=1.0):
    return Position(id=1, direction=direction, entry_time=0, entry_index=0,
                    entry_price=entry, quantity=quantity, stop_loss=stop,
                    take_profit=target, risk_reward=2.0, risk_pct=1.0, reason=2,
                    worst_price=entry, best_price=entry)


class ParamsTest(unittest.TestCase):
    def test_values_are_cast_to_the_field_type(self):
        params = Params.from_dict({"pyramiding": "7", "t1_en": 0, "spread": 1})
        self.assertEqual(params.pyramiding, 7)
        self.assertIs(params.t1_en, False)
        self.assertEqual(params.spread, 1.0)

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(Params.from_dict({"not_a_field": 1}), Params())

    def test_strict_mode_rejects_uncastable_values(self):
        with self.assertRaises(ParamError):
            Params.from_dict({"pyramiding": "many"}, strict=True)

    def test_lenient_mode_keeps_the_base_value(self):
        self.assertEqual(Params.from_dict({"pyramiding": "many"}).pyramiding, 100)

    def test_base_is_not_mutated(self):
        base = Params()
        Params.from_dict({"pyramiding": 3}, base=base)
        self.assertEqual(base.pyramiding, 100)


class TimeframeTest(unittest.TestCase):
    def setUp(self):
        # two hours of 5m bars, then a 10-day hole, then two more hours
        first = np.arange(0, 7200, 300, dtype=np.int64)
        self.epoch = np.concatenate([first, first + 10 * 86400])
        n = self.epoch.size
        self.o = np.full(n, 10.0)
        self.h = np.full(n, 12.0)
        self.l = np.full(n, 9.0)
        self.c = np.full(n, 11.0)
        self.v = np.ones(n)
        self.holes, self.closures = tf.find_breaks(self.epoch)

    def test_a_long_gap_is_a_hole_not_a_closure(self):
        self.assertEqual(len(self.holes), 1)
        self.assertEqual(self.closures, [])
        self.assertEqual(self.holes[0]["i"], 23)

    def test_a_bucket_never_spans_a_hole(self):
        times, *_ = tf.resample(self.epoch, self.o, self.h, self.l, self.c, self.v,
                                "1D", self.holes)
        self.assertEqual(len(times), 2)          # one day each side, never merged

    def test_resampling_preserves_volume_and_extremes(self):
        _, o, h, l, c, v = tf.resample(self.epoch, self.o, self.h, self.l, self.c,
                                       self.v, "1h", self.holes)
        self.assertEqual(v.sum(), self.v.sum())
        self.assertTrue((h <= self.h.max()).all() and (l >= self.l.min()).all())

    def test_holes_are_reindexed_onto_a_slice(self):
        moved = tf.reindex_holes(self.holes, 10, self.epoch.size)
        self.assertEqual(moved[0]["i"], 13)


class SeriesTest(unittest.TestCase):
    def _series(self, epoch):
        n = len(epoch)
        column = np.arange(n, dtype=np.float64) + 1
        return CandleSeries.from_columns(np.asarray(epoch, dtype=np.int64),
                                         column, column, column, column, column)

    def test_window_is_at_least_one_bar_wide(self):
        series = self._series(range(0, 3000, 300))
        self.assertEqual(series.window(1_000_000, 2_000_000)[1],
                         series.window(1_000_000, 2_000_000)[0] + 1)

    def test_window_covers_the_requested_range(self):
        series = self._series(range(0, 3000, 300))
        first, last = series.window(600, 1500)
        self.assertEqual((first, last), (2, 6))

    def test_out_of_order_timestamps_are_refused(self):
        series = self._series([0, 600, 300])
        self.assertFalse(series.strictly_increasing())
        self.assertTrue(issubclass(DataError, Exception))


class SpreadTest(unittest.TestCase):
    def test_a_round_turn_costs_one_full_spread(self):
        spread = SpreadModel(0.2)
        for direction in (1, -1):
            entry = spread.entry_price(100.0, direction)
            exit_ = spread.exit_price(100.0, direction)
            self.assertAlmostEqual(direction * (exit_ - entry), -0.2)

    def test_a_negative_spread_is_treated_as_zero(self):
        self.assertEqual(SpreadModel(-5).half, 0.0)


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.broker = IntrabarBroker()

    def bar(self, open_, high, low, close=None):
        return Bar(0, 0, open_, high, low, close if close is not None else open_)

    def test_stop_fills_first_when_both_levels_are_inside_one_bar(self):
        fill = self.broker.resolve(a_position(), self.bar(100.0, 103.0, 98.0))
        self.assertEqual(fill.reason, ExitReason.STOP_LOSS)
        self.assertEqual(fill.price, 99.0)

    def test_a_gap_through_the_stop_fills_at_the_open(self):
        fill = self.broker.resolve(a_position(), self.bar(95.0, 96.0, 94.0))
        self.assertEqual((fill.reason, fill.price), (ExitReason.STOP_LOSS, 95.0))

    def test_a_gap_through_the_target_fills_at_the_open(self):
        fill = self.broker.resolve(a_position(), self.bar(105.0, 106.0, 104.0))
        self.assertEqual((fill.reason, fill.price), (ExitReason.TAKE_PROFIT, 105.0))

    def test_a_quiet_bar_leaves_the_position_open(self):
        self.assertIsNone(self.broker.resolve(a_position(), self.bar(100.0, 101.0, 99.5)))

    def test_short_positions_mirror_the_long_rules(self):
        short = a_position(direction=-1, entry=100.0, stop=101.0, target=98.0)
        self.assertEqual(self.broker.resolve(short, self.bar(100.0, 102.0, 97.0)).reason,
                         ExitReason.STOP_LOSS)
        self.assertEqual(self.broker.resolve(short, self.bar(100.0, 100.5, 97.5)).reason,
                         ExitReason.TAKE_PROFIT)


class PositionTest(unittest.TestCase):
    def test_excursions_follow_the_trade_direction(self):
        long = a_position()
        long.track(high=105.0, low=95.0)
        self.assertEqual((long.worst_price, long.best_price), (95.0, 105.0))
        short = a_position(direction=-1)
        short.track(high=105.0, low=95.0)
        self.assertEqual((short.worst_price, short.best_price), (105.0, 95.0))

    def test_unrealized_pnl_is_signed_by_direction(self):
        self.assertEqual(a_position(quantity=2).unrealized(101.0), 2.0)
        self.assertEqual(a_position(direction=-1, quantity=2).unrealized(101.0), -2.0)


class AccountTest(unittest.TestCase):
    def test_booking_a_trade_moves_equity_and_records_a_point(self):
        account = Account(1000.0)
        trade = account.book(a_position(quantity=10), 60, 1, 101.0, ExitReason.TAKE_PROFIT)
        self.assertEqual(trade.pnl, 10.0)
        self.assertEqual(account.realized_equity, 1010.0)
        self.assertEqual(account.equity_points, [(60, 1010.0)])

    def test_size_risks_the_requested_fraction_of_equity(self):
        self.assertEqual(Account(1000.0).position_size(1000.0, 1.0, 2.0), 5.0)


class DailyLossLimitTest(unittest.TestCase):
    def test_it_trips_once_the_day_is_far_enough_down(self):
        limit = DailyLossLimit(True, 4.0)
        limit.start_day(1000.0)
        limit.observe(970.0)
        self.assertFalse(limit.blocks_entry)
        limit.observe(950.0)
        self.assertTrue(limit.blocks_entry)

    def test_a_new_day_clears_it(self):
        limit = DailyLossLimit(True, 4.0)
        limit.start_day(1000.0)
        limit.observe(900.0)
        limit.start_day(900.0)
        self.assertFalse(limit.blocks_entry)

    def test_disabled_limits_never_block(self):
        limit = DailyLossLimit(False, 4.0)
        limit.start_day(1000.0)
        limit.observe(1.0)
        self.assertFalse(limit.blocks_entry)


class GapPolicyTest(unittest.TestCase):
    def setUp(self):
        self.holes = [{"i": 5, "start": 0, "end": 1, "hours": 100.0}]

    def test_it_flattens_on_the_last_bar_before_a_hole(self):
        policy = GapPolicy(10, self.holes, flatten=True, warmup_bars=2)
        self.assertTrue(policy.flatten_at(5))
        self.assertFalse(policy.flatten_at(4))

    def test_entries_are_blocked_through_the_warmup(self):
        policy = GapPolicy(10, self.holes, flatten=True, warmup_bars=2)
        self.assertTrue(all(policy.blocks_entry(i) for i in (5, 6, 7)))
        self.assertFalse(policy.blocks_entry(8))

    def test_disabling_it_removes_both_effects(self):
        policy = GapPolicy(10, self.holes, flatten=False, warmup_bars=2)
        self.assertFalse(policy.flatten_at(5))
        self.assertFalse(policy.blocks_entry(6))


class StatisticsTest(unittest.TestCase):
    def _trades(self, pnls):
        trades, equity, points = [], 1000.0, []
        for index, pnl in enumerate(pnls):
            equity += pnl
            trades.append({"pnl": pnl, "direction": "long" if pnl > 0 else "short",
                           "reason": "Single Big Candle",
                           "exit_reason": "TP" if pnl > 0 else "SL",
                           "bars_held": 3, "equity_after": equity})
            points.append((index * 86400, equity))
        return trades, points, equity - 1000.0

    def test_headline_figures(self):
        trades, points, realized = self._trades([100.0, -50.0, 25.0])
        epoch = np.arange(0, 4 * 86400, 86400, dtype=np.int64)
        stats = compute_statistics(trades, points, 1000.0, realized, epoch)
        self.assertEqual(stats["total_trades"], 3)
        self.assertEqual(stats["wins"], 2)
        self.assertEqual(stats["profit_factor"], 2.5)
        self.assertEqual(stats["net_profit"], 75.0)
        self.assertEqual(stats["max_consec_wins"], 1)

    def test_an_empty_run_says_so_instead_of_dividing_by_zero(self):
        stats = compute_statistics([], [], 1000.0, 0.0, np.array([0, 86400]))
        self.assertEqual(stats["total_trades"], 0)

    def test_drawdown_is_measured_from_the_peak(self):
        trades, points, realized = self._trades([200.0, -100.0])
        epoch = np.arange(0, 3 * 86400, 86400, dtype=np.int64)
        stats = compute_statistics(trades, points, 1000.0, realized, epoch)
        self.assertEqual(stats["max_drawdown"], 100.0)


class ObjectiveTest(unittest.TestCase):
    def setUp(self):
        self.objective = Objective(min_trades=10, dd_cap=30.0, metric="calmar")

    def test_ruin_scores_below_anything_feasible(self):
        self.assertEqual(self.objective.score({"total_trades": 50, "ruined": True}), -8.0)

    def test_too_few_trades_is_graded_by_how_close_it_got(self):
        few = self.objective.score({"total_trades": 5, "return_pct": 10})
        fewer = self.objective.score({"total_trades": 2, "return_pct": 10})
        self.assertLess(fewer, few)

    def test_breaching_the_drawdown_cap_is_infeasible(self):
        self.assertLess(self.objective.score(
            {"total_trades": 50, "return_pct": 80, "max_drawdown_pct": 60, "calmar": 5}), 0)

    def test_a_feasible_candidate_scores_its_metric(self):
        self.assertEqual(self.objective.score(
            {"total_trades": 50, "return_pct": 80, "max_drawdown_pct": 20, "calmar": 3.5}), 3.5)


class SearchSpaceTest(unittest.TestCase):
    def test_ema_knobs_map_onto_the_params_field_names(self):
        params = build_params({"ema_fast": 200, "ema_slow": 900})
        self.assertEqual((params.ema_fast_len, params.ema_slow_len), (200, 900))

    def test_selecting_triggers_disables_the_others(self):
        params = build_params({}, groups=["t2", "exposure"])
        self.assertEqual((params.t1_en, params.t2_en, params.t3_en), (False, True, False))

    def test_without_trigger_groups_every_trigger_stays_as_it_was(self):
        params = build_params({}, groups=["exposure"])
        self.assertEqual((params.t1_en, params.t2_en, params.t3_en), (True, True, True))


class WalkForwardTest(unittest.TestCase):
    def test_n_parts_gives_n_minus_one_anchored_folds(self):
        folds = make_folds(0, 1000, 5)
        self.assertEqual(len(folds), 4)
        self.assertTrue(all(fold["is"][0] == 0 for fold in folds))       # anchored
        self.assertTrue(all(fold["is"][1] == fold["oos"][0] for fold in folds))

    def test_fewer_than_two_parts_is_rejected(self):
        with self.assertRaises(RuntimeError):
            make_folds(0, 1000, 1)

    def test_an_empty_range_is_rejected(self):
        with self.assertRaises(RuntimeError):
            make_folds(1000, 1000, 3)


class UtilTest(unittest.TestCase):
    def test_both_timestamp_formats_are_accepted(self):
        self.assertEqual(parse_timestamp("1970-01-02"), 86400)
        self.assertEqual(parse_timestamp("1970-01-02 00:01"), 86460)

    def test_no_bound_means_no_timestamp(self):
        self.assertIsNone(parse_timestamp(None))
        self.assertIsNone(parse_timestamp(""))

    def test_an_unparseable_date_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_timestamp("last tuesday")

    def test_downsampling_always_keeps_the_last_point(self):
        points = list(range(100))
        thinned = downsample(points, 10)
        self.assertLessEqual(len(thinned), 11)
        self.assertEqual(thinned[-1], 99)

    def test_short_series_are_left_alone(self):
        self.assertEqual(downsample([1, 2, 3], 10), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
