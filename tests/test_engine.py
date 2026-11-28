"""Engine behaviour on tiny hand-built bars where every number can be checked by hand."""
import math

import numpy as np
import pandas as pd
import pytest

from desk.engine.core import Costs, Engine, Risk, State, blank_intents, build_feed

T0 = pd.Timestamp("2024-01-01", tz="UTC")


def bars(rows, funding=0.0):
    idx = pd.date_range(T0, periods=len(rows), freq="h", name="time")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype="float64")
    df["funding"] = funding
    return df


def run(df, intents, costs=None, risk=None, **kw):
    costs = costs or Costs(taker_fee=0.0, maker_fee=0.0)
    risk = risk or Risk(guardian=False)
    feed = build_feed({"X": df}, {"X": intents}, slip_bps=0.0)
    eng = Engine(costs, risk, **kw)
    eng.run(feed, close_at_end=False)
    return eng


def test_intent_cannot_trade_on_its_own_bar():
    df = bars([[100, 101, 99, 100], [110, 111, 109, 110], [110, 111, 109, 110]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    eng = run(df, it)
    pos = eng.state.positions["X"]
    assert pos.entry_price == 110.0           # next bar's open, not the signal bar's close
    assert pos.entry_time == df.index[1].isoformat()


def test_risk_sizing_and_stop_loss_is_one_r():
    df = bars([[100, 100, 100, 100], [100, 101, 99.5, 100], [100, 100, 94, 95]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    eng = run(df, it, risk=Risk(guardian=False, max_pos_mult=100, max_gross_mult=100))
    t = eng.trades[0]
    assert t["qty"] == pytest.approx(50.0 / 5.0)      # $50 risk / $5 stop distance
    assert t["reason"] == "stop" and t["exit_price"] == 95.0
    assert t["pnl"] == pytest.approx(-50.0)
    assert t["r"] == pytest.approx(-1.0)


def test_stop_gap_fills_at_open_not_at_stop():
    df = bars([[100, 100, 100, 100], [100, 101, 99.5, 100], [90, 91, 89, 90]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    eng = run(df, it, risk=Risk(guardian=False, max_pos_mult=100, max_gross_mult=100))
    assert eng.trades[0]["exit_price"] == 90.0
    assert eng.trades[0]["r"] == pytest.approx(-2.0)


def test_resting_limit_needs_trade_through():
    it_rows = [[100, 100, 100, 100], [101, 102, 99.995, 101], [101, 102, 99.0, 101]]
    df = bars(it_rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
    eng = run(df, it, valid_bars=1)
    assert not eng.state.positions and not eng.trades       # touched but not through -> no fill, expired
    eng = run(df, it, valid_bars=2)
    assert eng.state.positions["X"].entry_price == 100.0     # filled on the second bar at the limit
    assert eng.state.positions["X"].maker_entry is True


def test_marketable_limit_fills_at_open_never_worse_than_limit():
    df = bars([[100, 100, 100, 100], [98, 99, 97, 98]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 90.0]
    eng = run(df, it)
    assert eng.state.positions["X"].entry_price == 98.0
    assert eng.state.positions["X"].maker_entry is False


def test_limit_fill_and_stop_in_same_bar_assumes_the_stop():
    df = bars([[100, 100, 100, 100], [101, 101, 94, 99]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 100.0, 95.0]
    eng = run(df, it)
    assert eng.trades and eng.trades[0]["reason"] == "stop"


def test_stop_beats_take_profit_when_both_touched():
    df = bars([[100, 100, 100, 100], [100, 100.5, 99.8, 100], [100, 111, 94, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop", "tp"]] = [1, 95.0, 110.0]
    eng = run(df, it)
    assert eng.trades[0]["reason"] == "stop"


def test_short_side_symmetry_and_funding_sign():
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [100, 100, 100, 100], [90, 90, 90, 90]], funding=0.001)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [-1, 105.0]
    it.loc[df.index[2], "exit"] = True
    eng = run(df, it, risk=Risk(guardian=False, max_pos_mult=100, max_gross_mult=100))
    t = eng.trades[0]
    qty = 50.0 / 5.0
    assert t["pnl_gross"] == pytest.approx(qty * 10.0)              # short from 100, covered at 90
    # positive funding: shorts RECEIVE. Charged on bars 1, 2 and 3? No: exit fills at the open of bar 3,
    # before that bar's funding, so two bars of funding at notional 100*qty.
    assert t["funding"] == pytest.approx(-2 * qty * 100.0 * 0.001)
    assert t["pnl"] == pytest.approx(qty * 10.0 + 2 * qty * 100.0 * 0.001)


def test_fees_and_slippage_reduce_pnl_and_reconcile_with_equity():
    rng = np.random.default_rng(1)
    n = 600
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    op = np.r_[close[0], close[:-1]]
    hi = np.maximum(op, close) * 1.003
    lo = np.minimum(op, close) * 0.997
    df = bars(np.c_[op, hi, lo, close].tolist(), funding=0.00002)
    it = blank_intents(df.index)
    sig = np.zeros(n, dtype=np.int8)
    sig[::7] = 1
    sig[3::11] = -1
    it["side"] = sig
    it["stop"] = np.where(sig > 0, close * 0.98, close * 1.02)
    it["tp"] = np.where(sig > 0, close * 1.03, close * 0.97)
    feed = build_feed({"X": df}, {"X": it}, slip_bps=4.0)
    eng = Engine(Costs(), Risk(guardian=False), max_hold=20)
    eng.run(feed, close_at_end=True)
    assert len(eng.trades) > 20
    total = sum(t["pnl"] for t in eng.trades)
    assert eng.state.equity == pytest.approx(10_000 + total, abs=1e-6)     # every dollar accounted for
    assert all(t["fees"] > 0 for t in eng.trades)
    free = Engine(Costs(taker_fee=0, maker_fee=0, slip_mult=0, funding_mult=0), Risk(guardian=False), max_hold=20)
    free.run(build_feed({"X": df}, {"X": it}, slip_bps=4.0), close_at_end=True)
    assert sum(t["pnl"] for t in free.trades) > total                      # costs always hurt


def test_guardian_daily_loss_halts_and_flattens():
    rows = [[100, 100, 100, 100]] * 3 + [[100, 100, 60, 60]] + [[60, 60, 60, 60]] * 4
    df = bars(rows)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 50.0]
    it.loc[df.index[5], ["side", "stop"]] = [1, 50.0]
    risk = Risk(guardian=True, risk_per_trade=0.05, max_pos_mult=5, max_gross_mult=5, max_stop_pct=0.9)
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(taker_fee=0, maker_fee=0), risk, log_events=True)
    eng.run(feed)
    assert eng.state.halted and "daily loss" in eng.state.halt_reason
    assert eng.trades[0]["reason"] == "guardian"
    assert not eng.state.positions and not eng.state.orders            # later signal was blocked
    assert any(e["event"] == "signal_blocked" for e in eng.events)


def test_guardian_three_losses_in_a_row():
    rows = []
    for _ in range(4):
        rows += [[100, 100, 100, 100], [100, 100, 98.9, 99]]
    df = bars(rows + [[100, 100, 100, 100]] * 2)
    it = blank_intents(df.index)
    for k in range(4):
        it.loc[df.index[2 * k], ["side", "stop"]] = [1, 99.0]
    eng = run(df, it, risk=Risk(guardian=True, max_pos_mult=100, max_gross_mult=100))
    assert len(eng.trades) == 3 and eng.state.halted and "in a row" in eng.state.halt_reason


def test_exposure_cap_limits_size():
    df = bars([[100, 100, 100, 100], [100, 100, 99.9, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 99.5]      # 0.5% stop -> would need $10k notional for $50 risk
    eng = run(df, it, risk=Risk(guardian=False, max_pos_mult=0.5))
    pos = eng.state.positions["X"]
    assert pos.qty * pos.entry_price == pytest.approx(5_000.0)
    assert pos.risk_usd == pytest.approx(25.0)


def test_state_round_trips_through_json_and_resumes_identically():
    rng = np.random.default_rng(7)
    n = 300
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
    op = np.r_[close[0], close[:-1]]
    df = bars(np.c_[op, np.maximum(op, close) * 1.002, np.minimum(op, close) * 0.998, close].tolist(), funding=1e-5)
    it = blank_intents(df.index)
    sig = np.zeros(n, dtype=np.int8)
    sig[::9] = 1
    it["side"] = sig
    it["limit"] = np.where(sig > 0, close * 0.999, np.nan)
    it["stop"] = close * 0.97
    it["tp"] = np.where(sig > 0, close * 1.04, np.nan)
    feed = build_feed({"X": df}, {"X": it}, slip_bps=2.0)
    one = Engine(Costs(), Risk(guardian=True), valid_bars=3, max_hold=30)
    one.run(feed)
    two = Engine(Costs(), Risk(guardian=True), valid_bars=3, max_hold=30)
    trades = []
    for i in range(n):                      # one bar at a time, state saved and reloaded every bar
        two.run(feed, i, i + 1)
        trades += two.trades
        import json
        st = State.from_json(json.loads(json.dumps(two.state.to_json())))
        two = Engine(Costs(), Risk(guardian=True), valid_bars=3, max_hold=30, state=st)
    assert len(trades) == len(one.trades) > 5
    assert st.equity == pytest.approx(one.state.equity, abs=1e-9)
    for a, b in zip(trades, one.trades):
        assert a["entry_time"] == b["entry_time"] and a["pnl"] == pytest.approx(b["pnl"], abs=1e-9)


def test_delisted_symbol_is_closed():
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [100, 100, 100, 100]])
    other = bars([[5, 5, 5, 5]] * 6)
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 90.0]
    feed = build_feed({"X": df, "Y": other}, {"X": it}, slip_bps=1.0)
    eng = Engine(Costs(), Risk(guardian=False))
    eng.run(feed)
    assert eng.trades and eng.trades[0]["reason"] == "delisted" and not eng.state.positions
    assert not math.isnan(eng.state.equity)
