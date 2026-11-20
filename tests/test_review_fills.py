"""Adversarial review, lens = fill realism, the Guardian and edge cases.

Tests marked `# DEFECT: <id>` FAIL on the engine as reviewed and should pass once the defect is fixed.
Everything else passes and pins down behaviour that was checked by hand.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from desk.engine.core import Costs, Engine, Risk, State, blank_intents, build_feed

T0 = pd.Timestamp("2024-01-01", tz="UTC")
FREE = dict(taker_fee=0.0, maker_fee=0.0)
BIG = dict(max_pos_mult=100, max_gross_mult=100)      # take the exposure caps out of the way


def bars(rows, funding=0.0, start=T0):
    idx = pd.date_range(start, periods=len(rows), freq="h", name="time")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype="float64")
    df["funding"] = funding
    return df


def run(df, intents, costs=None, risk=None, slip=0.0, close_at_end=False, tradable=None, **kw):
    costs = costs or Costs(**FREE)
    risk = risk or Risk(guardian=False)
    feed = build_feed({"X": df}, {"X": intents}, slip_bps=slip,
                      tradable=None if tradable is None else {"X": tradable})
    eng = Engine(costs, risk, log_events=True, **kw)
    eng.run(feed, close_at_end=close_at_end)
    return eng


def flat(n, px=100.0):
    return [[px, px, px, px]] * n


def kinds(eng):
    return [e["event"] for e in eng.events]


# =====================================================================================================
# resting limits and marketable limits, both sides
# =====================================================================================================
def test_short_resting_limit_needs_trade_through_and_fills_at_the_limit_as_maker():
    df = bars([[100, 100, 100, 100], [99, 100.005, 98, 99], [99, 101, 98, 99]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [-1, 100.0, 105.0]
    eng = run(df, it, valid_bars=1)
    assert not eng.state.positions and not eng.trades          # 0.5 bp above the limit is not a trade-through
    eng = run(df, it, valid_bars=2)
    pos = eng.state.positions["X"]
    assert pos.side == -1 and pos.entry_price == 100.0 and pos.maker_entry is True
    assert pos.entry_time == df.index[2].isoformat()


def test_trade_through_threshold_is_strict_on_both_sides():
    # exactly 1 bp through is NOT enough (strict inequality); a hair more is
    for low, filled in ((99.99, False), (99.9899, True)):
        df = bars([[100, 100, 100, 100], [101, 101, low, 101]])
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
        assert bool(run(df, it).state.positions) is filled
    for high, filled in ((100.01, False), (100.0101, True)):
        df = bars([[100, 100, 100, 100], [99, high, 99, 99]])
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "limit", "stop"]] = [-1, 100.0, 105.0]
        assert bool(run(df, it).state.positions) is filled


def test_short_marketable_limit_fills_at_open_never_worse_than_limit_and_pays_taker():
    df = bars([[100, 100, 100, 100], [102, 103, 101, 102]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [-1, 100.0, 110.0]
    eng = run(df, it, costs=Costs(taker_fee=0.001, maker_fee=0.0), slip=10.0)
    pos = eng.state.positions["X"]
    assert pos.entry_price == pytest.approx(102 * (1 - 0.001))     # open moved against the seller by 10 bp
    assert pos.maker_entry is False and pos.fees > 0               # crossing the book = taker


def test_marketable_limit_slippage_is_clipped_at_the_limit():
    # open 99.99, limit 100, slippage 10 bp would give 100.09 -> the limit protects the price
    df = bars([[100, 100, 100, 100], [99.99, 101, 99.9, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
    eng = run(df, it, slip=10.0)
    assert eng.state.positions["X"].entry_price == 100.0
    assert eng.state.positions["X"].maker_entry is False


def test_market_entry_pays_slippage_on_the_right_side_for_longs_and_shorts():
    for side, stop, expect in ((1, 90.0, 100 * 1.0005), (-1, 110.0, 100 * 0.9995)):
        df = bars(flat(3))
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "stop"]] = [side, stop]
        eng = run(df, it, slip=5.0)
        assert eng.state.positions["X"].entry_price == pytest.approx(expect)


# =====================================================================================================
# stops: gaps, the entry bar, exact touches, both sides
# =====================================================================================================
def test_market_entry_stopped_in_its_own_entry_bar_fills_at_the_stop_with_stop_slippage():
    # entry at the open of bar 1 (100), the same bar trades down to 94: out at the stop, 2 x slippage
    df = bars([[100, 100, 100, 100], [100, 100.5, 94, 96], [96, 96, 96, 96]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    eng = run(df, it, risk=Risk(guardian=False, **BIG), slip=10.0)
    t = eng.trades[0]
    assert t["reason"] == "stop" and t["entry_time"] == t["exit_time"] == df.index[1].isoformat()
    assert t["entry_price"] == pytest.approx(100.1)
    assert t["exit_price"] == pytest.approx(95.0 * (1 - 0.002))        # stop_slip_mult = 2
    assert t["bars_held"] == 0
    assert t["r"] == pytest.approx(-(100.1 - 95 * 0.998) / (100.1 - 95.0))


def test_short_stop_gap_fills_at_the_open_and_exact_touch_triggers():
    df = bars([[100, 100, 100, 100], [100, 100.5, 99, 100], [110, 111, 109, 110]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [-1, 105.0]
    eng = run(df, it, risk=Risk(guardian=False, **BIG))
    assert eng.trades[0]["reason"] == "stop" and eng.trades[0]["exit_price"] == 110.0
    assert eng.trades[0]["r"] == pytest.approx(-2.0)
    # high == stop exactly: counts as hit (pessimistic), filled at the stop
    df = bars([[100, 100, 100, 100], [100, 100.5, 99, 100], [100, 105.0, 99, 100]])
    eng = run(df, it, risk=Risk(guardian=False, **BIG))
    assert eng.trades[0]["reason"] == "stop" and eng.trades[0]["exit_price"] == 105.0


def test_maker_entry_whose_bar_also_trades_through_the_stop_is_stopped_short_side():
    df = bars([[100, 100, 100, 100], [99, 106, 98, 104]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [-1, 100.0, 105.0]
    eng = run(df, it)
    assert eng.trades[0]["reason"] == "stop" and eng.trades[0]["exit_price"] == 105.0


def test_stop_on_the_wrong_side_never_becomes_an_order():
    df = bars(flat(4))
    for side, limit, stop in ((1, np.nan, 101.0), (-1, np.nan, 99.0), (1, 98.0, 99.0), (-1, 102.0, 101.0),
                              (1, np.nan, np.nan), (1, np.nan, 100.0)):
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "limit", "stop"]] = [side, limit, stop]
        eng = run(df, it)
        assert not eng.state.positions and not eng.state.orders and not eng.trades
        assert "signal_blocked" in kinds(eng)


def test_stop_distance_is_rechecked_at_the_fill_price():
    # (a) the open gaps through the stop, (b) the gap leaves the stop 0.1% away, (c) 30% away
    for nxt_open in (94.0, 95.1, 140.0):
        df = bars([[100, 100, 100, 100], [nxt_open, nxt_open + 1, nxt_open - 0.01, nxt_open]])
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
        eng = run(df, it)
        assert not eng.state.positions and not eng.trades and "order_rejected" in kinds(eng)


def test_size_with_a_very_tight_and_a_very_wide_stop():
    df = bars(flat(3))
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 99.75]            # 0.25% stop: $50 risk would need $20k
    pos = run(df, it).state.positions["X"]
    assert pos.qty * pos.entry_price == pytest.approx(10_000.0)   # capped at 1 x equity
    assert pos.risk_usd == pytest.approx(25.0)                    # and R is measured on what is really at risk
    it.loc[df.index[0], ["side", "stop"]] = [1, 80.0]             # 20% stop
    pos = run(df, it).state.positions["X"]
    assert pos.qty * pos.entry_price == pytest.approx(250.0) and pos.risk_usd == pytest.approx(50.0)


# =====================================================================================================
# take-profit and the stop-vs-target rule
# =====================================================================================================
def test_take_profit_needs_trade_through_and_fills_at_the_target_as_maker():
    for high, done in ((110.011, False), (110.0111, True)):
        df = bars([[100, 100, 100, 100], [100, 101, 99.5, 100], [100, high, 99.5, 100]])
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "stop", "tp"]] = [1, 95.0, 110.0]
        eng = run(df, it, costs=Costs(taker_fee=0.001, maker_fee=0.0002), risk=Risk(guardian=False, **BIG))
        assert bool(eng.trades) is done
        if done:
            t = eng.trades[0]
            assert t["reason"] == "take_profit" and t["exit_price"] == 110.0
            assert t["fees"] == pytest.approx(t["qty"] * (100 * 0.001 + 110 * 0.0002))   # taker in, maker out


def test_stop_beats_take_profit_for_shorts_and_on_a_gap_through_the_target():
    df = bars([[100, 100, 100, 100], [100, 100.5, 99.8, 100], [100, 106, 89, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop", "tp"]] = [-1, 105.0, 90.0]
    assert run(df, it).trades[0]["reason"] == "stop"
    # long: bar opens ABOVE the target and later trades down to the stop -> the engine still books the stop
    df = bars([[100, 100, 100, 100], [100, 100.5, 99.8, 100], [112, 113, 94, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop", "tp"]] = [1, 95.0, 110.0]
    assert run(df, it).trades[0]["reason"] == "stop"


def test_take_profit_in_the_entry_bar_market_entry_yes_maker_entry_no():
    # market entry at the open, later the same bar trades through the target: allowed
    df = bars([[100, 100, 100, 100], [100, 103, 99.5, 102], [102, 102, 102, 102]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop", "tp"]] = [1, 95.0, 102.0]
    eng = run(df, it)
    assert eng.trades[0]["reason"] == "take_profit" and eng.trades[0]["exit_price"] == 102.0
    # resting-limit entry: the high may have come BEFORE the fill, so no target in the entry bar
    df = bars([[101, 101, 101, 101], [101, 103, 99.5, 100.5], [100.5, 100.6, 100.4, 100.5]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop", "tp"]] = [1, 100.0, 95.0, 102.0]
    eng = run(df, it)
    assert not eng.trades and eng.state.positions["X"].maker_entry is True


def test_take_profit_after_a_maker_entry_bar_is_not_filled_better_than_the_target():
    # DEFECT: FILL-1
    # Long limit 100, target 101, stop 98. Bar 1 opens 100.5, dips to 99.5 (fill at 100) and closes at 102.8.
    # Whatever the path inside the bar, price crossed 101 AFTER the fill (fill 100 < 101 < close 102.8),
    # so the resting sell limit at 101 is done at 101. The engine skips the target in the entry bar and
    # then hands the position the next OPEN (102.8): +1.4R booked instead of +0.5R.
    df = bars([[100.5, 100.5, 100.5, 100.5], [100.5, 103.0, 99.5, 102.8], [102.8, 103.0, 102.5, 102.9]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop", "tp"]] = [1, 100.0, 98.0, 101.0]
    eng = run(df, it, risk=Risk(guardian=False, **BIG))
    t = eng.trades[0]
    assert t["reason"] == "take_profit"
    assert t["exit_price"] == pytest.approx(101.0)        # a resting limit never gets price improvement
    assert t["r"] == pytest.approx(0.5)


def test_take_profit_on_a_gap_open_fills_at_the_target_not_at_the_open_short():
    # DEFECT: FILL-1
    # Short from 100, buy-limit target at 95. The market reopens at 90 after a quiet hour. A resting buy
    # limit at 95 is filled at 95 on the way down; the engine books 90.
    df = bars([[100, 100, 100, 100], [100, 100.5, 99.5, 100], [90, 91, 89, 90]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop", "tp"]] = [-1, 105.0, 95.0]
    eng = run(df, it, risk=Risk(guardian=False, **BIG))
    t = eng.trades[0]
    assert t["reason"] == "take_profit"
    assert t["exit_price"] == pytest.approx(95.0)
    assert t["r"] == pytest.approx(1.0)


def test_target_on_the_wrong_side_of_a_maker_entry_is_not_a_free_exit_at_the_open():
    # DEFECT: FILL-2
    # Long limit 100 (maker fill), "target" 50 - already far below the market, i.e. not a target at all.
    # The engine closes at the next open with the MAKER fee and NO slippage, which is cheaper than the
    # signal exit every other strategy pays (taker fee + slippage). A marketable sell crosses the book.
    df = bars([[101, 101, 101, 101], [101, 101, 99.5, 100.5], [100.5, 100.6, 100.4, 100.5]])
    costs = Costs(taker_fee=0.0005, maker_fee=0.0002)
    risk = Risk(guardian=False, **BIG)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
    it.loc[df.index[1], "exit"] = True
    honest = run(df, it, costs=costs, risk=risk, slip=10.0).trades[0]        # exit at the next open, as a taker
    assert honest["exit_price"] == pytest.approx(100.5 * (1 - 0.001))
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop", "tp"]] = [1, 100.0, 95.0, 50.0]
    eng = run(df, it, costs=costs, risk=risk, slip=10.0)
    if not eng.trades:                       # acceptable fix: reject / drop a target that is not beyond the entry
        return
    assert eng.trades[0]["pnl"] <= honest["pnl"] + 1e-9


# =====================================================================================================
# trailing stop
# =====================================================================================================
def test_trailing_stop_only_tightens_never_crosses_the_market_and_acts_from_the_next_bar():
    rows = [[100, 100, 100, 100], [100, 101, 99.5, 100], [100, 104, 100, 104], [104, 105, 102.5, 103],
            [103, 103.5, 102.5, 103], [103, 103, 101.9, 102.5]]
    df = bars(rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    it.loc[df.index[1], "trail"] = 90.0       # looser than 95 -> ignored
    it.loc[df.index[2], "trail"] = 102.0      # tighter, below the close (104) -> accepted, live from bar 3
    it.loc[df.index[3], "trail"] = 103.5      # above the close (103) -> ignored
    it.loc[df.index[4], "trail"] = 101.0      # looser than 102 -> ignored
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(guardian=False))
    seen = []
    for i in range(len(df)):
        eng.run(feed, i, i + 1)
        seen.append(eng.state.positions["X"].stop if "X" in eng.state.positions else None)
    assert seen[:5] == [None, 95.0, 102.0, 102.0, 102.0]
    # bar 2's own low (100) is below the new 102 stop but the stop set at its close cannot act on it
    t = eng.trades[0]
    assert t["exit_time"] == df.index[5].isoformat() and t["exit_price"] == 102.0 and t["stop0"] == 95.0


def test_short_trailing_stop_mirror():
    rows = [[100, 100, 100, 100], [100, 100.5, 99, 100], [100, 100, 96, 96], [96, 99.0, 95, 97]]
    df = bars(rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [-1, 105.0]
    it.loc[df.index[1], "trail"] = 110.0      # looser -> ignored
    it.loc[df.index[2], "trail"] = 98.0       # tighter and above the close (96) -> accepted
    eng = run(df, it)
    assert eng.trades[0]["reason"] == "stop" and eng.trades[0]["exit_price"] == 98.0


# =====================================================================================================
# time stop, order expiry, duplicate intents, re-entry, last bar
# =====================================================================================================
@pytest.mark.parametrize("n", [1, 2, 5])
def test_time_stop_holds_exactly_max_hold_bars(n):
    df = bars(flat(12))
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    eng = run(df, it, max_hold=n)
    t = eng.trades[0]
    assert t["reason"] == "time" and t["bars_held"] == n
    assert t["entry_time"] == df.index[1].isoformat() and t["exit_time"] == df.index[1 + n].isoformat()


@pytest.mark.parametrize("n", [1, 2, 4])
def test_limit_order_works_for_exactly_valid_bars_bars(n):
    # the limit is only traded through on bar k (1-based after the signal bar)
    for k in range(1, 6):
        rows = [[101, 101, 101, 101]] + [[101, 102, 100.5, 101]] * (k - 1) + [[101, 102, 99, 101]] + flat(2, 101)
        df = bars(rows)
        it = blank_intents(df.index)
        it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
        eng = run(df, it, valid_bars=n)
        assert bool(eng.state.positions) is (k <= n)
        assert not eng.state.orders or k > n


def test_entry_intents_are_ignored_while_an_order_or_a_position_exists():
    rows = [[101, 101, 101, 101]] * 3 + [[101, 101, 99, 100]] + flat(3, 100)
    df = bars(rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
    it.loc[df.index[1], ["side", "limit", "stop"]] = [1, 100.5, 90.0]     # ignored: an order is working
    it.loc[df.index[4], ["side", "stop"]] = [-1, 120.0]                   # ignored: a position is open
    eng = run(df, it, valid_bars=5)
    pos = eng.state.positions["X"]
    assert pos.side == 1 and pos.entry_price == 100.0 and pos.stop == 95.0 and not eng.state.orders
    assert kinds(eng).count("order_created") == 1


def test_reentry_after_a_stop_out_waits_for_the_next_bar():
    # stopped during bar 2; bar 2 also emits a fresh long at its close -> filled at the open of bar 3
    df = bars([[100, 100, 100, 100], [100, 100.5, 99.5, 100], [100, 100, 94, 96], [97, 98, 96.5, 97], [97, 97, 97, 97]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    it.loc[df.index[2], ["side", "stop"]] = [1, 90.0]
    eng = run(df, it)
    assert eng.trades[0]["reason"] == "stop" and eng.trades[0]["exit_time"] == df.index[2].isoformat()
    pos = eng.state.positions["X"]
    assert pos.entry_time == df.index[3].isoformat() and pos.entry_price == 97.0


def test_exit_flagged_on_the_last_bar():
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [100, 103, 100, 102]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    it.loc[df.index[2], "exit"] = True
    eng = run(df, it)                                         # paper bot: stays pending for the next bar
    assert eng.state.positions["X"].exit_pending == "signal" and not eng.trades
    eng = run(df, it, slip=10.0, close_at_end=True)           # backtest: closed at the last close, with slippage
    t = eng.trades[0]
    assert t["reason"] == "end_of_data" and t["exit_price"] == pytest.approx(102 * (1 - 0.001))
    assert eng.state.equity == pytest.approx(10_000 + t["pnl"])


def test_exit_signal_fills_at_the_next_open_before_that_bar_can_stop_it():
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [99, 99, 80, 85]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    it.loc[df.index[1], "exit"] = True
    eng = run(df, it)
    assert eng.trades[0]["reason"] == "signal" and eng.trades[0]["exit_price"] == 99.0


# =====================================================================================================
# the Guardian
# =====================================================================================================
G = dict(guardian=True, risk_per_trade=0.05, max_pos_mult=5, max_gross_mult=5, max_stop_pct=0.9)


def _one_long(rows, extra=None, start=T0):
    df = bars(rows, start=start)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 50.0]         # qty = 500 / 50 = 10 -> $10 per point
    for i, vals in (extra or {}).items():
        for k, v in vals.items():
            it.loc[df.index[i], k] = v
    return df, it


def test_daily_loss_limit_boundary_is_minus_three_percent_inclusive():
    for close, halted in ((70.01, False), (70.0, True)):
        df, it = _one_long(flat(2) + [[100, 100, close, close]] + flat(2, close))
        eng = run(df, it, risk=Risk(**G))
        assert eng.state.halted is halted                    # 10 x 30 = $300 = 3.00% of $10,000


def test_daily_loss_is_measured_from_the_days_starting_equity_not_from_the_trade():
    # day 1: the position loses 2.9% and is carried overnight. Day 2: a further 2.9%. Never -3% in a day.
    start = pd.Timestamp("2024-01-01 21:00", tz="UTC")
    rows = flat(2) + [[100, 100, 71, 71]] + flat(3, 71) + [[71, 71, 42, 42]] + flat(2, 42)
    df, it = _one_long(rows, start=start)
    it.loc[df.index[0], "stop"] = 20.0
    eng = run(df, it, risk=Risk(**{**G, "risk_per_trade": 0.08}))
    assert not eng.state.halted and "X" in eng.state.positions
    assert eng.state.equity == pytest.approx(10_000 - 10 * 58)


def test_halt_cancels_orders_flattens_at_the_next_open_and_blocks_entries_until_the_next_utc_day():
    rows = flat(3) + [[100, 100, 60, 60], [58, 58, 58, 58]] + flat(30, 58)
    df = bars(rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 50.0]
    y = bars(flat(len(rows), 10.0))
    ity = blank_intents(y.index)
    ity.loc[y.index[2], ["side", "limit", "stop"]] = [1, 9.0, 8.0]       # resting order alive at the halt
    ity.loc[y.index[6], ["side", "stop"]] = [1, 8.0]                     # same day -> blocked
    ity.loc[y.index[23], ["side", "stop"]] = [1, 8.0]                    # 23:00 of the halt day -> blocked
    ity.loc[y.index[24], ["side", "stop"]] = [1, 8.0]                    # 00:00 next day -> accepted
    feed = build_feed({"X": df, "Y": y}, {"X": it, "Y": ity}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(**G), valid_bars=10, log_events=True)
    eng.run(feed, 0, 4)
    assert eng.state.halted and not eng.state.orders                     # the resting Y order is gone
    assert eng.state.positions["X"].exit_pending == "guardian"
    eng.run(feed, 4, 24)
    assert eng.trades[0]["reason"] == "guardian" and eng.trades[0]["exit_price"] == 58.0
    assert eng.state.halted and not eng.state.positions and not eng.state.orders
    assert sum(e["event"] == "signal_blocked" for e in eng.events) == 2
    eng.run(feed, 24, 26)
    assert not eng.state.halted and eng.state.consec_losses == 0
    assert eng.state.positions["Y"].entry_time == y.index[25].isoformat()


def test_sticky_halt_survives_the_day_change_until_a_human_resumes():
    rows = flat(3) + [[100, 100, 60, 60], [58, 58, 58, 58]] + flat(60, 58)
    df, it = _one_long(rows, extra={30: {"side": 1, "stop": 40.0}, 50: {"side": 1, "stop": 40.0}})
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(**{**G, "halt_sticky": True}))
    eng.run(feed, 0, 40)
    assert eng.state.halted and not eng.state.positions and len(eng.trades) == 1   # day 2 signal was blocked
    eng.resume()
    eng.run(feed, 40, len(df))
    assert not eng.state.halted and eng.state.positions["X"].entry_time == df.index[51].isoformat()


def test_resume_on_the_day_of_a_daily_loss_halt_actually_lets_the_bot_trade():
    # DEFECT: GRD-1
    # Halt at 03:00 on the daily loss limit. A human reviews and calls Engine.resume() at 08:00 the same
    # UTC day. day_start_equity is not rebased, so the very next processed bar sees "still -4% on the day",
    # halts again and cancels the order that was just accepted. With halt_sticky=True (live / paper) the
    # human override is a silent no-op for the rest of the day, and has to be repeated after midnight.
    rows = flat(3) + [[100, 100, 60, 60], [60, 60, 60, 60]] + flat(15, 60)
    df, it = _one_long(rows, extra={8: {"side": 1, "stop": 55.0}})
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(**{**G, "halt_sticky": True}), log_events=True)
    eng.run(feed, 0, 8)
    assert eng.state.halted and "daily loss" in eng.state.halt_reason and not eng.state.positions
    eng.resume()
    eng.run(feed, 8, 12)
    assert not eng.state.halted, eng.state.halt_reason
    assert "X" in eng.state.positions


def test_three_losses_in_a_row_counts_across_symbols_and_a_winner_resets_the_count():
    # loss, loss, WIN, loss, loss -> no halt; then a third consecutive loss -> halt
    seq = [99.0, 99.0, 102.0, 99.0, 99.0, 99.0]
    rows = []
    for px in seq:
        rows += [[100, 100, 100, 100], [100, max(100, px), min(100, px), px]]
    df = bars(rows + flat(2))
    it = blank_intents(df.index)
    for k in range(len(seq)):
        it.loc[df.index[2 * k], ["side", "stop", "tp"]] = [1, 99.5, 101.5]
    eng = run(df, it, risk=Risk(guardian=True, daily_loss_limit=0.5, **BIG))
    assert [t["pnl"] > 0 for t in eng.trades] == [False, False, True, False, False, False]
    assert eng.state.halted and "3 losing trades in a row" in eng.state.halt_reason


def test_a_halt_at_2300_utc_pauses_nothing():
    # NOTE (design, see finding GRD-2): the non-sticky halt lifts at the first bar of the next UTC day, so a
    # third straight loss at 23:00 flattens the book but the very next signal (00:00) is taken again.
    start = pd.Timestamp("2024-01-01 17:00", tz="UTC")
    rows = []
    for _ in range(3):
        rows += [[100, 100, 100, 100], [100, 100, 98.9, 99]]
    rows += [[100, 100, 100, 100], [100, 100, 100, 100], [100, 100, 100, 100]]
    df = bars(rows, start=start)
    it = blank_intents(df.index)
    for k in range(3):
        it.loc[df.index[2 * k], ["side", "stop"]] = [1, 99.0]
    it.loc[df.index[7], ["side", "stop"]] = [1, 99.0]                   # 00:00 next day
    assert df.index[5].hour == 22 and df.index[7].hour == 0
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(guardian=True, **BIG))
    eng.run(feed, 0, 6)
    assert eng.state.halted and len(eng.trades) == 3
    eng.run(feed, 6, len(df))
    assert not eng.state.halted and "X" in eng.state.positions          # trading again two bars later


# =====================================================================================================
# delisting, late listing, missing hours, bad prices
# =====================================================================================================
def test_symbol_that_stops_printing_cancels_its_order_and_closes_its_position_with_a_penalty():
    x = bars(flat(4))
    y = bars(flat(8, 5.0))
    it = blank_intents(x.index)
    it.loc[x.index[0], ["side", "stop"]] = [1, 90.0]
    feed = build_feed({"X": x, "Y": y}, {"X": it}, slip_bps=3.0)
    eng = Engine(Costs(**FREE), Risk(guardian=False), log_events=True)
    eng.run(feed)
    t = eng.trades[0]
    assert t["reason"] == "delisted" and t["exit_time"] == y.index[4].isoformat()
    assert t["exit_price"] == pytest.approx(100 * (1 - 3.0 * 2 * 5 / 1e4))        # 10 x normal slippage
    # a resting order on the dead symbol is cancelled, never filled
    it = blank_intents(x.index)
    it.loc[x.index[3], ["side", "stop"]] = [1, 90.0]
    feed = build_feed({"X": x, "Y": y}, {"X": it}, slip_bps=3.0)
    eng = Engine(Costs(**FREE), Risk(guardian=False), log_events=True)
    eng.run(feed)
    assert not eng.trades and not eng.state.positions and not eng.state.orders


def test_one_late_bar_is_treated_as_a_delisting():
    # NOTE (see finding BOT-1): the engine cannot tell "delisted" from "this symbol's newest candle has not
    # arrived yet". In the downloaded data PF_POPCATUSD ends one hour before the other symbols, so a bot
    # that builds its feed from ragged files would have liquidated a POPCAT position at 10 x slippage.
    x = bars(flat(5))
    y = bars(flat(6, 5.0))                     # Y already has the newest hour, X does not yet
    it = blank_intents(x.index)
    it.loc[x.index[0], ["side", "stop"]] = [1, 90.0]
    feed = build_feed({"X": x, "Y": y}, {"X": it}, slip_bps=3.0)
    eng = Engine(Costs(**FREE), Risk(guardian=False))
    eng.run(feed)
    assert eng.trades and eng.trades[0]["reason"] == "delisted"


def test_symbol_listed_mid_history_cannot_trade_before_its_first_bar():
    y = bars(flat(10, 5.0))
    x = bars(flat(4), start=T0 + pd.Timedelta(hours=6))
    it = blank_intents(y.index)                                 # intents on the LONG index, before X exists
    it.loc[y.index[2], ["side", "stop"]] = [1, 90.0]
    it.loc[y.index[5], ["side", "stop"]] = [1, 90.0]            # bar before the listing
    it.loc[y.index[6], ["side", "stop"]] = [1, 90.0]            # first real bar
    feed = build_feed({"X": x, "Y": y}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(guardian=False))
    eng.run(feed)
    assert eng.state.positions["X"].entry_time == y.index[7].isoformat()


def test_entry_is_not_filled_on_a_bar_flagged_untradable():
    # DEFECT: FILL-3
    # runner.load_market folds `bar_missing` and universe membership into `tradable` so that there are
    # "no new entries ... on hours the venue printed no candle". The engine tests tradable[] on the SIGNAL
    # bar only. A signal on a good bar followed by a missing hour (prices forward-filled, nothing traded),
    # or by the first hour of a month in which the symbol has left the top 10, is filled anyway.
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [100, 100, 100, 100], [120, 121, 119, 120]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    tradable = pd.Series([True, False, False, True], index=df.index)     # bars 1-2: no candle from the venue
    eng = run(df, it, tradable=tradable)
    assert not any(p.entry_time == df.index[1].isoformat() for p in eng.state.positions.values())


def test_nan_open_rejects_the_entry_and_does_not_poison_equity():
    df = bars([[100, 100, 100, 100], [np.nan, 101, 99, 100], [100, 100, 100, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    eng = run(df, it)
    assert not eng.state.positions and math.isfinite(eng.state.equity) and "order_rejected" in kinds(eng)


def test_side_must_be_plus_or_minus_one():
    # DEFECT: ENG-1
    # side = 2 (for example two boolean signals added together) is accepted as-is. Stop distance is doubled,
    # so quantity and notional are halved while PnL per point is unchanged: fees are charged on half the
    # real exposure and the 1 x equity position cap lets through a position twice as large as allowed.
    df = bars(flat(2) + [[100, 110, 100, 110]] + flat(2, 110))
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [2, 99.0]          # 1% stop: $50 risk needs $5,000 notional
    it.loc[df.index[2], "exit"] = True
    eng = run(df, it, costs=Costs(taker_fee=0.001, maker_fee=0.0))
    assert eng.trades, "either reject side=2 or treat it as +1"
    t = eng.trades[0]
    assert abs(t["side"]) == 1
    assert t["pnl_gross"] == pytest.approx(t["qty"] * 10.0)
    assert t["fees"] == pytest.approx(t["qty"] * (100 + 110) * 0.001)
    assert t["qty"] * t["entry_price"] == pytest.approx(5_000.0)


# =====================================================================================================
# State round trip and bar-by-bar resumption (the paper bot)
# =====================================================================================================
def _random_market(seed, n=24 * 14):
    rng = np.random.default_rng(seed)
    data, intents = {}, {}
    for k, s in enumerate(["A", "B", "C", "D"]):
        start = T0 + pd.Timedelta(hours=0 if k < 3 else 50)          # D lists late
        m = n if k != 2 else n - 90                                   # C is delisted early
        m = m if k < 3 else n - 50
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, m)))
        op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.0005, m))
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.004, m)))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.004, m)))
        df = bars(np.c_[op, hi, lo, close].tolist(), funding=2e-5, start=start)
        it = blank_intents(df.index)
        u = rng.random(m)
        side = np.where(u < 0.10, 1, np.where(u < 0.20, -1, 0)).astype(np.int8)
        it["side"] = side
        use_limit = rng.random(m) < 0.5
        it["limit"] = np.where(use_limit & (side != 0), close * (1 - side * 0.003), np.nan)
        it["stop"] = close * (1 - side * 0.02)
        it["tp"] = np.where(rng.random(m) < 0.6, close * (1 + side * 0.03), np.nan)
        it["trail"] = np.where(rng.random(m) < 0.3, close * (1 + rng.normal(0, 0.01, m)), np.nan)
        it["exit"] = rng.random(m) < 0.03
        data[s], intents[s] = df, it
    return build_feed(data, intents, slip_bps=3.0)


def _norm(rows):
    """Lists of dicts with NaN in them, made comparable (NaN != NaN)."""
    return json.dumps(rows, sort_keys=True, default=float)


def test_bar_by_bar_resume_through_json_matches_one_run_with_halts_limits_trails_and_delisting():
    reasons, flags = set(), set()
    for seed, sticky in ((1, False), (2, False), (3, True), (4, False), (5, False), (6, True)):
        feed = _random_market(seed)
        risk = dict(guardian=True, risk_per_trade=0.01, halt_sticky=sticky)
        kw = dict(valid_bars=3, max_hold=20)
        # sticky runs: a human resumes every 36 hours, at the same bars in both runs
        cuts = list(range(0, feed.n, 36)) + [feed.n] if sticky else [0, feed.n]
        one = Engine(Costs(), Risk(**risk), log_events=True, **kw)
        for a, b in zip(cuts[:-1], cuts[1:]):
            if sticky:
                one.resume()
            one.run(feed, a, b)
        two = Engine(Costs(), Risk(**risk), log_events=True, **kw)
        trades, events, curve = [], [], []
        for i in range(feed.n):
            if sticky and i in cuts:
                two.resume()
            two.run(feed, i, i + 1)
            trades += two.trades
            events += two.events
            curve.append(two.equity_curve[i])
            st = two.state
            flags |= {k for k, v in (("order", bool(st.orders)), ("halted", st.halted),
                                     ("trailed", any(p.stop != p.stop0 for p in st.positions.values())),
                                     ("exit_pending", any(p.exit_pending for p in st.positions.values()))) if v}
            blob = json.dumps(st.to_json(), allow_nan=False)         # strict JSON: no NaN / Infinity leaks
            two = Engine(Costs(), Risk(**risk), log_events=True, state=State.from_json(json.loads(blob)), **kw)
        reasons |= {t["reason"] for t in one.trades}
        assert len(trades) == len(one.trades) > 20
        assert _norm(trades) == _norm(one.trades)
        assert _norm(events) == _norm(one.events)
        assert np.array_equal(np.array(curve), one.equity_curve, equal_nan=True)
        assert _norm(two.state.to_json()) == _norm(one.state.to_json())
    # the scenarios really exercised what the test name claims
    assert flags == {"order", "halted", "trailed", "exit_pending"}
    assert {"stop", "take_profit", "guardian", "time", "signal", "delisted"} <= reasons


def test_state_json_keeps_pending_limit_order_trailing_stop_and_halt_fields():
    rows = flat(2) + [[100, 103, 100, 103]] + flat(2, 103)
    df = bars(rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    it.loc[df.index[2], "trail"] = 101.0
    y = bars(flat(len(rows), 10.0))
    ity = blank_intents(y.index)
    ity.loc[y.index[3], ["side", "limit", "stop"]] = [-1, 11.0, 12.0]
    feed = build_feed({"X": df, "Y": y}, {"X": it, "Y": ity}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(guardian=True, halt_sticky=True), valid_bars=5)
    eng.run(feed)
    eng.state.halted, eng.state.halt_reason, eng.state.halt_day = True, "manual", 19723
    st = State.from_json(json.loads(json.dumps(eng.state.to_json(), allow_nan=False)))
    assert st.positions["X"].stop == 101.0 and st.positions["X"].stop0 == 95.0
    assert math.isnan(st.positions["X"].tp)
    od = st.orders["Y"]
    assert (od.side, od.limit, od.stop, od.valid_left) == (-1, 11.0, 12.0, 4) and math.isnan(od.tp)
    assert (st.halted, st.halt_reason, st.halt_day) == (True, "manual", 19723)
    assert st.to_json() == eng.state.to_json()


def test_replaying_a_bar_that_was_already_processed_changes_nothing():
    # DEFECT: BOT-2
    # State.last_time records the last processed bar but Engine.run never looks at it. If the paper bot is
    # started twice in an hour (cron retry, restart after a crash that happened after the state was saved)
    # the bar is applied again: funding is charged twice and the time stop ages by two bars.
    df = bars(flat(6), funding=0.001)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(**FREE), Risk(guardian=False), max_hold=10)
    eng.run(feed, 0, 3)
    before = eng.state.to_json()
    try:
        eng.run(feed, 2, 3)                   # same bar again
    except Exception:
        return                                # refusing loudly is an acceptable fix
    assert eng.state.to_json() == before
