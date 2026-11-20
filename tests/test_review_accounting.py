"""Adversarial review, lens = MONEY ACCOUNTING.

Everything here is recomputed independently of desk.engine / desk.audit (by hand on tiny bars, or by
a slow reference simulator / ledger rebuilt from raw bars). Tests marked `# DEFECT: <id>` FAIL on the
code as reviewed and should pass once the defect is fixed. All other tests pin behaviour verified correct.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from desk.audit import harness, scoring
from desk.engine.core import Costs, Engine, Risk, blank_intents, build_feed, make_base
from desk.engine.metrics import losing_streak, summarize
from desk.engine.runner import Market, load_market, run

ROOT = Path(__file__).resolve().parents[1]
HAVE_DATA = (ROOT / "data" / "kraken_futures" / "1h" / "PF_SOLUSD.parquet").exists()
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="market data not downloaded")

T0 = pd.Timestamp("2024-01-01", tz="UTC")
TAKER, MAKER = 0.0005, 0.0002
S = 10.0 / 1e4          # 10 bps of slippage in the hand-built tests
EQ0 = 10_000.0
BTC = "PF_XBTUSD"


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def bars(rows, funding=0.0, t0=T0):
    idx = pd.date_range(t0, periods=len(rows), freq="h", name="time")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype="float64")
    df["funding"] = funding
    return df


def go(df, it, costs=None, risk=None, slip=10.0, close_at_end=False, **kw):
    """One symbol 'X', default Kraken fees, 10 bps slippage, Guardian off unless a Risk is given."""
    feed = build_feed({"X": df}, {"X": it}, slip_bps=slip)
    eng = Engine(costs or Costs(), risk or Risk(guardian=False), **kw)
    eng.run(feed, close_at_end=close_at_end)
    return eng


def intents(df, rows: dict):
    it = blank_intents(df.index)
    for i, kv in rows.items():
        for k, v in kv.items():
            it.loc[df.index[i], k] = v
    return it


FLAT = [100, 100, 100, 100]


# =====================================================================================================
# 1. Fill prices, fees and funding for every fill type (hand arithmetic)
# =====================================================================================================
@pytest.mark.parametrize("side", [1, -1])
def test_market_entry_and_signal_exit_pay_slippage_fees_and_funding(side):
    df = bars([FLAT, [100, 101, 99, 100.5], [102, 102, 102, 102], [102, 102, 102, 102]], funding=0.0001)
    stop = 90.0 if side > 0 else 110.0
    eng = go(df, intents(df, {0: {"side": side, "stop": stop}, 1: {"exit": True}}))
    t = eng.trades[0]
    entry = 100 * (1 + side * S)                       # buy higher / sell lower
    exit_ = 102 * (1 - side * S)                       # sell lower / buy back higher
    qty = 50.0 / abs(entry - stop)                     # 0.5% of $10k at risk
    fees = qty * (entry + exit_) * TAKER
    funding = side * qty * 100 * 0.0001                # bar 1 only: the exit fills at the open of bar 2
    assert t["entry_price"] == pytest.approx(entry) and t["exit_price"] == pytest.approx(exit_)
    assert t["qty"] == pytest.approx(qty) and t["reason"] == "signal"
    assert t["fees"] == pytest.approx(fees) and t["funding"] == pytest.approx(funding)
    pnl = side * qty * (exit_ - entry) - fees - funding
    assert t["pnl"] == pytest.approx(pnl) and t["r"] == pytest.approx(pnl / 50.0)
    assert eng.state.equity == pytest.approx(EQ0 + pnl)
    assert (t["funding"] > 0) == (side > 0)            # longs pay a positive rate, shorts receive it


@pytest.mark.parametrize("side,last_bar,base", [
    (1, [100, 100, 94, 95], 95.0),        # long stop touched inside the bar -> stop price
    (1, [90, 91, 89, 90], 90.0),          # long stop gapped through -> the open
    (-1, [100, 106, 100, 105], 105.0),    # short stop touched
    (-1, [110, 111, 109, 110], 110.0),    # short stop gapped
])
def test_stop_fills_at_stop_or_gap_open_with_double_slippage_and_charges_that_bars_funding(side, last_bar, base):
    df = bars([FLAT, [100, 100.4, 99.6, 100], last_bar], funding=0.0001)
    stop = 95.0 if side > 0 else 105.0
    t = go(df, intents(df, {0: {"side": side, "stop": stop}})).trades[0]
    entry = 100 * (1 + side * S)
    qty = 50.0 / abs(entry - stop)
    exit_ = base * (1 - side * 2 * S)                  # stop_slip_mult = 2, always against us
    assert t["reason"] == "stop" and t["exit_price"] == pytest.approx(exit_)
    assert t["fees"] == pytest.approx(qty * (entry + exit_) * TAKER)
    assert t["funding"] == pytest.approx(side * qty * (100 + last_bar[0]) * 0.0001)   # entry bar AND stop bar
    assert t["pnl"] == pytest.approx(side * qty * (exit_ - entry) - t["fees"] - t["funding"])
    assert t["r"] < -1.0                                # a stopped trade loses more than 1R after costs


@pytest.mark.parametrize("side,open_,expect", [
    (1, 99.95, 100.0),            # open + slippage would be 100.04995 -> capped at the limit
    (1, 98.0, 98.0 * (1 + S)),    # well through the limit -> open plus slippage
    (-1, 100.05, 100.0),
    (-1, 102.0, 102.0 * (1 - S)),
])
def test_marketable_limit_fills_at_open_plus_slippage_never_worse_than_limit_and_pays_taker(side, open_, expect):
    df = bars([FLAT, [open_, open_ + 0.3, open_ - 0.3, open_]])
    stop = 90.0 if side > 0 else 110.0
    eng = go(df, intents(df, {0: {"side": side, "limit": 100.0, "stop": stop}}))
    p = eng.state.positions["X"]
    assert p.entry_price == pytest.approx(expect) and p.maker_entry is False
    assert p.fees == pytest.approx(p.qty * expect * TAKER)


def test_resting_limit_and_take_profit_are_maker_fills_at_their_price_and_fee_mult_scales_both():
    df = bars([FLAT, [100, 100.5, 98.5, 99.5], [99.5, 105, 99.4, 104.5]], funding=-0.0002)
    eng = go(df, intents(df, {0: {"side": 1, "limit": 99.0, "stop": 90.0, "tp": 104.0}}), costs=Costs(fee_mult=2.0))
    t = eng.trades[0]
    qty = 50.0 / 9.0
    assert t["entry_price"] == 99.0 and t["exit_price"] == 104.0 and t["reason"] == "take_profit"
    assert t["maker_entry"] is True and t["qty"] == pytest.approx(qty)
    assert t["fees"] == pytest.approx(qty * (99 + 104) * MAKER * 2.0)
    assert t["funding"] == pytest.approx(qty * (100 + 99.5) * -0.0002)      # negative rate: the long RECEIVES
    assert t["pnl"] == pytest.approx(qty * 5 - t["fees"] - t["funding"])


def test_guardian_exit_fills_at_next_open_with_single_slippage_and_taker_fee():
    rows = [FLAT] * 3 + [[100, 100, 60, 60]] + [[60, 60, 60, 60]] * 3
    df = bars(rows)
    risk = Risk(guardian=True, risk_per_trade=0.05, max_pos_mult=5, max_gross_mult=5, max_stop_pct=0.9)
    eng = go(df, intents(df, {0: {"side": 1, "stop": 50.0}}), risk=risk)
    t = eng.trades[0]
    entry, exit_ = 100 * (1 + S), 60 * (1 - S)
    qty = 500.0 / (entry - 50.0)
    assert t["reason"] == "guardian" and t["exit_time"] == df.index[4].isoformat()
    assert t["exit_price"] == pytest.approx(exit_) and t["qty"] == pytest.approx(qty)
    assert t["fees"] == pytest.approx(qty * (entry + exit_) * TAKER)
    assert eng.state.equity == pytest.approx(EQ0 + t["pnl"])


def test_end_of_data_closes_at_last_close_minus_slippage_and_delisting_at_ten_times_slippage():
    df = bars([FLAT, [100, 101, 99, 100.5], [100.5, 103, 100, 102]], funding=0.0001)
    it = intents(df, {0: {"side": 1, "stop": 90.0}})
    t = go(df, it, close_at_end=True).trades[0]
    qty = 50.0 / (100 * (1 + S) - 90)
    assert t["reason"] == "end_of_data" and t["exit_price"] == pytest.approx(102 * (1 - S))
    assert t["funding"] == pytest.approx(qty * (100 + 100.5) * 0.0001)      # both held bars, including the last

    other = bars([[5, 5, 5, 5]] * 6)                                        # keeps the clock running after X stops
    feed = build_feed({"X": df, "Y": other}, {"X": it}, slip_bps=10.0)
    eng = Engine(Costs(), Risk(guardian=False))
    eng.run(feed)
    d = eng.trades[0]
    assert d["reason"] == "delisted" and d["exit_time"] == other.index[3].isoformat()
    assert d["exit_price"] == pytest.approx(102 * (1 - 10 * S))             # slip x stop_slip_mult(2) x 5
    assert d["fees"] == pytest.approx(qty * (100 * (1 + S) + d["exit_price"]) * TAKER)
    assert eng.state.equity == pytest.approx(EQ0 + d["pnl"])


def test_cost_multipliers_scale_each_cost_and_nothing_else():
    df = bars([FLAT, [100, 101, 99, 100.5], [102, 102, 102, 102], [102, 102, 102, 102]], funding=0.0003)
    it = intents(df, {0: {"side": 1, "stop": 90.0}, 1: {"exit": True}})
    base = go(df, it).trades[0]
    f2 = go(df, it, costs=Costs(fee_mult=2.0)).trades[0]
    u2 = go(df, it, costs=Costs(funding_mult=2.0)).trades[0]
    s2 = go(df, it, costs=Costs(slip_mult=2.0)).trades[0]
    free = go(df, it, costs=Costs(fee_mult=0, slip_mult=0, funding_mult=0)).trades[0]
    assert f2["fees"] == pytest.approx(2 * base["fees"]) and f2["funding"] == pytest.approx(base["funding"])
    assert u2["funding"] == pytest.approx(2 * base["funding"]) and u2["fees"] == pytest.approx(base["fees"])
    assert s2["entry_price"] == pytest.approx(100 * (1 + 2 * S)) and s2["exit_price"] == pytest.approx(102 * (1 - 2 * S))
    assert free["fees"] == 0 and free["funding"] == 0 and free["entry_price"] == 100 and free["exit_price"] == 102
    assert free["pnl"] == pytest.approx(50.0 / 10 * 2)


# =====================================================================================================
# 2. Position sizing and the caps
# =====================================================================================================
def test_sizing_risks_half_a_percent_and_min_max_stop_distance_reject_orders():
    df = bars([FLAT, [100, 100.05, 99.95, 100]])
    ok = go(df, intents(df, {0: {"side": 1, "stop": 98.0}}), slip=0.0).state.positions["X"]
    assert ok.qty == pytest.approx(25.0) and ok.risk_usd == pytest.approx(50.0)        # $50 / $2
    assert not go(df, intents(df, {0: {"side": 1, "stop": 99.9}}), slip=0.0).state.positions     # 0.1% < min 0.2%
    assert not go(df, intents(df, {0: {"side": 1, "stop": 70.0}}), slip=0.0).state.positions     # 30% > max 25%
    capped = go(df, intents(df, {0: {"side": 1, "stop": 99.7}}), slip=0.0).state.positions["X"]  # wants $16.7k
    assert capped.qty * capped.entry_price == pytest.approx(EQ0)                       # max_pos_mult = 1 x equity
    assert capped.risk_usd == pytest.approx(30.0)                                      # R is measured on real risk


@pytest.mark.parametrize("gross_mult,third_notional", [(3.0, 10_000.0), (2.5, 5_000.0), (2.0, None)])
def test_gross_exposure_cap_shrinks_then_rejects_the_last_position(gross_mult, third_notional):
    df = bars([FLAT, [100, 100.05, 99.95, 100]])
    it = intents(df, {0: {"side": 1, "stop": 99.5}})                                   # each wants $10k notional
    feed = build_feed({"A": df, "B": df, "C": df}, {"A": it, "B": it, "C": it}, slip_bps=0.0)
    eng = Engine(Costs(), Risk(guardian=False, max_gross_mult=gross_mult))
    eng.run(feed)
    pos = eng.state.positions
    assert pos["A"].qty * 100 == pytest.approx(10_000) and pos["B"].qty * 100 == pytest.approx(10_000)
    if third_notional is None:
        assert "C" not in pos
    else:
        assert pos["C"].qty * 100 == pytest.approx(third_notional)
        assert pos["C"].risk_usd == pytest.approx(third_notional * 0.005)
    assert sum(p.qty * p.last_price for p in pos.values()) <= gross_mult * EQ0 + 1e-6


# =====================================================================================================
# 3. Ledger rebuilt from raw bars: every trade's fees / funding / pnl / R and the whole hourly equity curve
# =====================================================================================================
def rebuild_and_check_ledger(trades, arrays, times, equity, costs: Costs, equity0=EQ0, i0=0, market_side=None):
    """Recompute each trade from the raw bar arrays and rebuild the mark-to-market curve from the trade list.

    Funding is owed for every bar the position is open at any time: from the entry bar to the bar before an
    exit that fills at the open (signal / time / guardian / delisted), or through the exit bar itself
    (stop / take_profit / end_of_data)."""
    pos_of = {t: i for i, t in enumerate(times)}
    realised, open_mtm = np.zeros(len(times)), np.zeros(len(times))
    for tr in trades:
        a = arrays[tr["symbol"]]
        e, x, side, qty = pos_of[tr["entry_time"]], pos_of[tr["exit_time"]], tr["side"], tr["qty"]
        assert qty > 0 and x >= e
        fee_in = (costs.maker_fee if tr["maker_entry"] else costs.taker_fee) * costs.fee_mult
        fee_out = (costs.maker_fee if tr["reason"] == "take_profit" else costs.taker_fee) * costs.fee_mult
        entry_fee = qty * tr["entry_price"] * fee_in
        fees = entry_fee + qty * tr["exit_price"] * fee_out
        last_funded = x if tr["reason"] in ("stop", "take_profit", "end_of_data") else x - 1
        accrual = [side * qty * a["o"][b] * a["funding"][b] * costs.funding_mult for b in range(e, last_funded + 1)]
        gross = side * qty * (tr["exit_price"] - tr["entry_price"])
        pnl = gross - fees - sum(accrual)
        assert tr["fees"] == pytest.approx(fees, rel=1e-9, abs=1e-9)
        assert tr["funding"] == pytest.approx(sum(accrual), rel=1e-9, abs=1e-9)
        assert tr["pnl_gross"] == pytest.approx(gross, rel=1e-9, abs=1e-9)
        assert tr["pnl"] == pytest.approx(pnl, rel=1e-9, abs=1e-9)
        assert tr["risk_usd"] == pytest.approx(qty * abs(tr["entry_price"] - tr["stop0"]), rel=1e-9)
        assert tr["r"] == pytest.approx(pnl / tr["risk_usd"], rel=1e-9, abs=1e-9)
        assert qty * tr["entry_price"] <= 1.0 * equity0 * (1 + 1e-9)                   # max_pos_mult
        slip_x = a["slip_bps"][x] * costs.slip_mult / 1e4
        if tr["reason"] in ("signal", "time", "guardian"):
            assert tr["exit_price"] == pytest.approx(a["o"][x] * (1 - side * slip_x), rel=1e-12)
        if tr["reason"] == "end_of_data":
            assert tr["exit_price"] == pytest.approx(a["c"][x] * (1 - side * slip_x), rel=1e-12)
        if market_side is not None and side == market_side:
            slip_e = a["slip_bps"][e] * costs.slip_mult / 1e4
            assert tr["entry_price"] == pytest.approx(a["o"][e] * (1 + side * slip_e), rel=1e-12)
            assert tr["maker_entry"] is False
        realised[x:] += pnl
        paid = 0.0
        for k, b in enumerate(range(e, x)):                                           # still open at these closes
            paid += accrual[k]
            open_mtm[b] += side * qty * (a["c"][b] - tr["entry_price"]) - entry_fee - paid
    rebuilt = equity0 + realised + open_mtm
    np.testing.assert_allclose(np.asarray(equity)[i0:], rebuilt[i0:], rtol=0, atol=1e-6)
    return rebuilt


def _random_market(seed, n=1500):
    rng = np.random.default_rng(seed)
    dfs, its = {}, {}
    for k, (sym, length) in enumerate([("A", n), ("B", n), ("C", n - 400)]):      # C stops printing: delisting
        close = (50 + 30 * k) * np.exp(np.cumsum(rng.normal(0, 0.012, length)))
        op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.001, length))     # small open gaps
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.004, length)))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.004, length)))
        df = bars(np.c_[op, hi, lo, close].tolist())
        df["funding"] = rng.normal(0.00002, 0.0002, length)                        # both signs
        it = blank_intents(df.index)
        u = rng.random(length)
        side = np.where(u < 0.06, 1, np.where(u < 0.12, -1, 0)).astype(np.int8)
        it["side"] = side
        it["limit"] = np.where(side < 0, close * 1.003, np.nan)                    # longs at market, shorts by limit
        it["stop"] = np.where(side > 0, close * 0.975, close * 1.03)
        it["tp"] = np.where(side > 0, close * 1.04, np.where(rng.random(length) < 0.5, close * 0.97, np.nan))
        it["trail"] = np.where(rng.random(length) < 0.1, close * np.where(rng.random(length) < 0.5, 0.99, 1.01), np.nan)
        it["exit"] = rng.random(length) < 0.02
        dfs[sym], its[sym] = df, it
    return dfs, its


@pytest.mark.parametrize("guardian", [False, True])
def test_every_trade_and_the_hourly_equity_curve_rebuild_from_raw_bars_synthetic(guardian):
    dfs, its = _random_market(11)
    slip = {s: pd.Series(4.0 + 3.0 * k, index=df.index) for k, (s, df) in enumerate(dfs.items())}
    feed = build_feed(dfs, its, slip_bps=slip)
    costs = Costs(fee_mult=1.3, slip_mult=1.7, funding_mult=0.6)
    eng = Engine(costs, Risk(guardian=guardian), valid_bars=3, max_hold=30)
    eng.run(feed, close_at_end=True)
    reasons = {t["reason"] for t in eng.trades}
    want = {"stop", "take_profit", "signal", "time", "delisted"} | ({"guardian"} if guardian else set())
    assert want <= reasons and len(eng.trades) > 80
    assert {t["side"] for t in eng.trades} == {1, -1} and any(t["maker_entry"] for t in eng.trades)
    arrays = {s: dict(o=f.o, c=f.c, funding=f.funding, slip_bps=f.slip_bps) for s, f in feed.sym.items()}
    rebuild_and_check_ledger(eng.trades, arrays, feed.times, eng.equity_curve, costs, market_side=1)
    assert eng.state.equity == pytest.approx(EQ0 + sum(t["pnl"] for t in eng.trades), abs=1e-6)
    assert not eng.state.positions


def test_costs_never_help_in_the_random_market():
    dfs, its = _random_market(5)
    def total(c):
        e = Engine(c, Risk(guardian=False), valid_bars=3, max_hold=30)
        e.run(build_feed(dfs, its, slip_bps=6.0), close_at_end=True)
        return sum(t["pnl"] for t in e.trades), sum(t["fees"] for t in e.trades)
    base, fees = total(Costs())
    dbl, fees2 = total(Costs(fee_mult=2.0))
    assert fees > 0 and dbl < base and dbl == pytest.approx(base - fees, rel=0.05)   # ~ one more set of fees


# =====================================================================================================
# 4. Independent slow reference simulator for the reference strategy on REAL bars, one symbol
# =====================================================================================================
def _wilder_atr(df, n):
    h, l, c = df["high"].tolist(), df["low"].tolist(), df["close"].tolist()
    out, prev = [], None
    for i in range(len(c)):
        tr = h[i] - l[i]
        if i > 0:
            tr = max(tr, abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        prev = tr if prev is None else prev + (tr - prev) / n
        out.append(prev if i >= n - 1 else float("nan"))
    return out


def _half_gap_slippage(df):
    """docs/PROTOCOL.md + costs.py: half the venue's $10k bid/ask gap, 7-day rolling median, lagged one bar."""
    mid = (df["ask_10k"] + df["bid_10k"]) / 2
    half = (df["ask_10k"] - df["bid_10k"]) / mid / 2 * 1e4
    half = half.where(half >= 0)
    med = half.rolling(168, min_periods=24).median().shift(1)
    first = half.first_valid_index()
    early = float(half[first:first + pd.Timedelta(days=180)].median()) * 1.5
    out = med.copy()
    out[out.index < first + pd.Timedelta(hours=25)] = early
    return out.ffill().fillna(early).clip(0.5, 60.0)


def reference_donchian(df, sym, start, end, n=96, atr_n=24, k_atr=3.0, fee_mult=1.0, slip_mult=1.0, funding_mult=1.0,
                       guardian=True):
    """Long-only breakout, one symbol, written from the docs with plain Python floats and one loop."""
    uni = json.loads((ROOT / "data" / "universe.json").read_text())["months"]
    atr = _wilder_atr(df, atr_n)
    highs = df["high"].tolist()
    prior_high = [max(highs[i - n:i]) if i >= n else float("nan") for i in range(len(highs))]
    slip = _half_gap_slippage(df).tolist()
    O, H, L, C, F = (df[c].tolist() for c in ("open", "high", "low", "close", "funding"))
    missing = df["bar_missing"].tolist()
    cash, pos, order, trades, curve = EQ0, None, None, [], {}
    halted, halt_day, losses_in_row, day, day_start, equity, flatten = False, None, 0, None, EQ0, EQ0, False

    def close(px, t, reason):
        nonlocal cash, pos, losses_in_row
        fee = pos["qty"] * px * TAKER * fee_mult
        pos["fees"] += fee
        cash += pos["qty"] * (px - pos["entry"]) - fee
        pnl = pos["qty"] * (px - pos["entry"]) - pos["fees"] - pos["funding"]
        trades.append(dict(entry_time=pos["t"].isoformat(), exit_time=t.isoformat(), entry_price=pos["entry"],
                           exit_price=px, qty=pos["qty"], fees=pos["fees"], funding=pos["funding"], pnl=pnl,
                           reason=reason, r=pnl / pos["risk"]))
        losses_in_row = losses_in_row + 1 if pnl < 0 else 0
        pos = None

    last = None
    for i, t in enumerate(df.index):
        if t < start or t >= end:
            continue
        last = i
        if t.floor("D") != day:
            day, day_start = t.floor("D"), equity
            if halted and day > halt_day:
                halted, losses_in_row = False, 0
        s = slip[i] * slip_mult / 1e4
        opened_now = False
        if pos and flatten:                                           # Guardian exit at this open
            close(O[i] * (1 - s), t, "guardian")
        flatten = False
        if order is not None:                                         # market order from the previous close
            stop, order = order, None
            px = O[i] * (1 + s)
            dist = px - stop
            if not halted and dist > 0 and 0.002 <= dist / px <= 0.25:
                qty = min(EQ0 * 0.005 / dist, EQ0 / px)
                if qty * px >= 10.0:
                    cash -= qty * px * TAKER * fee_mult
                    pos = dict(qty=qty, entry=px, stop=stop, fees=qty * px * TAKER * fee_mult, funding=0.0, t=t,
                               risk=qty * dist, mark=px)
                    opened_now = True
        if pos:
            pay = pos["qty"] * O[i] * F[i] * funding_mult             # longs pay a positive rate
            cash -= pay
            pos["funding"] += pay
            if L[i] <= pos["stop"]:
                gapped = O[i] <= pos["stop"] and not opened_now
                close((O[i] if gapped else pos["stop"]) * (1 - 2 * s), t, "stop")
            else:
                pos["mark"] = C[i]
        band = k_atr * atr[i]
        if pos:
            if not math.isnan(band) and pos["stop"] < C[i] - band < C[i]:
                pos["stop"] = C[i] - band                             # trailing stop only tightens
        elif not math.isnan(band) and not math.isnan(prior_high[i]) and C[i] > prior_high[i] and band > 0:
            if not halted and not missing[i] and sym in uni.get(t.strftime("%Y-%m"), ()):
                order = C[i] - band
        equity = cash + (pos["qty"] * (pos["mark"] - pos["entry"]) if pos else 0.0)
        curve[t] = equity
        if guardian and not halted and (equity / day_start - 1 <= -0.03 or losses_in_row >= 3):
            halted, halt_day, order, flatten = True, day, None, pos is not None
    if pos:
        close(pos["mark"] * (1 - slip[last] * slip_mult / 1e4), df.index[last], "end_of_data")
        curve[df.index[last]] = cash
    return trades, pd.Series(curve)


@needs_data
@pytest.mark.parametrize("sym,a,b,guardian,mult", [
    ("PF_SOLUSD", "2024-01-01", "2024-07-01", False, 1.0),
    ("PF_SOLUSD", "2025-01-01", "2025-07-01", True, 1.0),
    ("PF_DOGEUSD", "2025-01-01", "2025-10-01", True, 2.0),     # every cost doubled
    ("PF_XBTUSD", "2023-10-01", "2024-07-01", True, 1.0),
])
def test_engine_matches_independent_reference_simulator_on_real_bars(sym, a, b, guardian, mult):
    from desk.data import store
    from desk.strategies.ref_donchian import STRATEGY
    start, end = ts(a), ts(b)
    market = load_market(end=end, syms=[sym])
    costs = Costs(fee_mult=mult, slip_mult=mult, funding_mult=mult)
    res = run(STRATEGY, None, market, start, end, costs, Risk(guardian=guardian))
    ref_trades, ref_eq = reference_donchian(store.load(sym, end=end), sym, start, end, fee_mult=mult, slip_mult=mult,
                                            funding_mult=mult, guardian=guardian)
    assert len(res["trades"]) == len(ref_trades) >= 20
    for got, want in zip(res["trades"], ref_trades):
        assert (got["entry_time"], got["exit_time"], got["reason"]) == (want["entry_time"], want["exit_time"], want["reason"])
        for k in ("entry_price", "exit_price", "qty", "fees", "funding", "pnl", "r"):
            assert got[k] == pytest.approx(want[k], rel=1e-9, abs=1e-9), k
    np.testing.assert_allclose(res["equity"].to_numpy(), ref_eq.reindex(res["equity"].index).to_numpy(), atol=1e-6)
    s = res["summary"]
    assert s["pnl_usd"] == pytest.approx(sum(t["pnl"] for t in ref_trades), abs=1e-6)
    assert s["total_return"] == pytest.approx(s["pnl_usd"] / EQ0)
    assert s["fees_usd"] == pytest.approx(sum(t["fees"] for t in ref_trades))
    assert s["funding_usd"] == pytest.approx(sum(t["funding"] for t in ref_trades))


@needs_data
def test_real_bars_long_short_limit_tp_exit_ledger_rebuilds_dollar_for_dollar():
    from desk.strategies.base import Strategy

    class Probe(Strategy):
        """Not a strategy to trade: it only exercises every fill type on real bars."""
        name, valid_bars, max_hold, params = "probe", 2, 36, {}

        def intents(self, data, p):
            out = {}
            for s, df in data.items():
                it = blank_intents(df.index)
                c = df["close"]
                r = c.pct_change(6)
                side = np.where(r > 0.02, 1, np.where(r < -0.02, -1, 0))
                it["side"] = side.astype(np.int8)
                it["limit"] = np.where(side < 0, c * 1.002, np.nan)          # shorts rest a limit above the market
                it["stop"] = np.where(side > 0, c * 0.97, c * 1.03)
                it["tp"] = np.where(side > 0, c * 1.05, c * 0.96)
                it["exit"] = (c.pct_change(3).abs() < 0.0005).to_numpy()
                out[s] = it
            return out

    start, end = ts("2024-02-01"), ts("2024-06-01")
    market = load_market(end=end, syms=["PF_SOLUSD", "PF_ETHUSD", "PF_XBTUSD"])
    costs = Costs()
    res = run(Probe(), None, market, start, end, costs, Risk(guardian=True))
    trades = res["trades"]
    assert len(trades) > 100 and {t["side"] for t in trades} == {1, -1}
    assert {"stop", "take_profit", "signal", "time", "guardian"} <= {t["reason"] for t in trades}
    assert any(t["maker_entry"] for t in trades) and any(t["funding"] < 0 for t in trades)
    idx = market.base.index
    i0 = int(idx.searchsorted(start))
    full = np.full(len(idx), np.nan)
    full[i0:i0 + len(res["equity"])] = res["equity"].to_numpy()
    times = [t.isoformat() for t in idx]
    rebuilt = rebuild_and_check_ledger(trades, market.base.arrays, times, full[:i0 + len(res["equity"])], costs,
                                       i0=i0, market_side=1)
    assert res["summary"]["pnl_usd"] == pytest.approx(rebuilt[i0 + len(res["equity"]) - 1] - EQ0, abs=1e-6)
    # shorts collect positive funding, longs pay it: check the sign against the raw column on one trade each
    for side in (1, -1):
        t = next(t for t in trades if t["side"] == side and t["reason"] == "stop" and t["exit_time"] > t["entry_time"])
        a = market.base.arrays[t["symbol"]]
        e, x = times.index(t["entry_time"]), times.index(t["exit_time"])
        assert t["funding"] == pytest.approx(side * t["qty"] * float(np.dot(a["o"][e:x + 1], a["funding"][e:x + 1])))


# =====================================================================================================
# 5. metrics.summarize
# =====================================================================================================
def _curve(daily_closes, t0="2025-01-20"):
    """Hourly curve that is flat inside each day and ends each day at the given equity."""
    idx = pd.date_range(ts(t0), periods=24 * len(daily_closes), freq="h")
    return pd.Series(np.repeat(np.asarray(daily_closes, dtype=float), 24), index=idx)


def test_summarize_returns_drawdown_sharpe_for_a_non_compounding_account():
    closes = [10_000, 10_100, 10_050, 10_200, 9_900, 10_300]
    eq = _curve(closes)
    s = summarize(eq, [], EQ0)
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    assert s["pnl_usd"] == pytest.approx(300.0) and s["total_return"] == pytest.approx(0.03)
    assert s["annual_return"] == pytest.approx(0.03 / years)                 # simple, not compounded
    assert s["max_dd"] == pytest.approx(-300 / EQ0)                          # 10,200 -> 9,900, as a share of START equity
    assert s["calmar"] == pytest.approx(s["annual_return"] / 0.03)
    def sharpe(changes):
        return changes.mean() / changes.std(ddof=1) * math.sqrt(365)       # daily changes / start equity, 365 days
    with_first_day = sharpe(np.diff([EQ0] + closes) / EQ0)                  # correct: six days, the first one flat
    without_first_day = sharpe(np.diff(closes) / EQ0)                       # today: day one is dropped (ACC-MET-1)
    assert s["sharpe"] == pytest.approx(with_first_day) or s["sharpe"] == pytest.approx(without_first_day)
    assert s["worst_day"] == pytest.approx(-0.03)


def test_summarize_worst_month_includes_first_and_last_partial_months():
    idx = pd.date_range(ts("2025-01-20"), ts("2025-03-10 23:00"), freq="h")
    eq = pd.Series(EQ0, index=idx)
    eq[idx >= ts("2025-01-25")] -= 400          # January (partial, first): -4%
    eq[idx >= ts("2025-02-10")] += 100          # February: +1%
    eq[idx >= ts("2025-03-05")] -= 200          # March (partial, last): -2%
    s = summarize(eq, [], EQ0)
    assert s["monthly"] == {"2025-01": -0.04, "2025-02": 0.01, "2025-03": -0.02}
    assert s["worst_month"] == pytest.approx(-0.04) and s["best_month"] == pytest.approx(0.01)
    assert sum(s["monthly"].values()) == pytest.approx(s["total_return"])


def test_summarize_trade_statistics_streak_and_exposure():
    eq = _curve([10_000, 10_000, 10_010])
    gross = pd.Series(0.0, index=eq.index)
    gross.iloc[10:28] = 2_000.0                                             # in the market 18 of 72 hours
    pn = [5, -1, -2, 0, -3, -4, -5, 20]                                    # a flat trade breaks a losing streak
    trades = [dict(pnl=float(p), r=p / 50, side=1, bars_held=3, fees=0.1, funding=0.0, pnl_gross=p + 0.1,
                   maker_entry=False, reason="stop", symbol="X") for p in pn]
    s = summarize(eq, trades, EQ0, gross)
    assert s["exposure"] == pytest.approx(18 / 72) and s["avg_gross_leverage"] == pytest.approx(18 * 0.2 / 72)
    assert s["longest_losing_streak"] == 3 and losing_streak([-1, -1, 1, -1]) == 2
    assert s["win_rate"] == pytest.approx(2 / 8) and s["profit_factor"] == pytest.approx(25 / 15)
    assert s["avg_r"] == pytest.approx(np.mean(pn) / 50) and s["fees_usd"] == pytest.approx(0.8)


def test_summarize_ignores_everything_that_happens_on_the_first_day():
    # DEFECT: ACC-MET-1
    # A -5% first day followed by two flat days. The daily series is built with .diff() and no starting
    # point, so the first day's result is silently dropped from Sharpe, Sortino and worst_day.
    eq = _curve([9_500, 9_500, 9_500])
    eq.iloc[0] = 10_000.0                       # the account starts the window at $10,000
    s = summarize(eq, [], EQ0)
    assert s["total_return"] == pytest.approx(-0.05)
    assert s["worst_day"] == pytest.approx(-0.05)
    assert s["sharpe"] < 0


def test_regime_attribution_adds_up_to_the_total_return():
    # DEFECT: ACC-MET-1
    # harness.by_regime uses the same .diff() and loses the first day, so the per-regime P&L the bear/chop
    # score is built from does not add up to the reported total.
    eq = _curve([10_200, 10_100, 10_300, 10_250])
    eq.iloc[0] = 10_000.0
    labels = pd.Series(["bear", "chop", "bull", "chop"], index=pd.date_range(eq.index[0], periods=4, freq="D"))
    reg = harness.by_regime(eq, labels, EQ0)
    assert sum(v["days"] for v in reg.values()) == 4
    assert sum(v["pnl_pct"] for v in reg.values()) == pytest.approx(0.025)
    assert reg["bear"]["pnl_pct"] == pytest.approx(0.02)


def test_sortino_uses_downside_deviation_over_all_days():
    # DEFECT: ACC-MET-2
    # Downside deviation is sqrt(mean(min(r, 0)^2)) over ALL days; the code averages over losing days only,
    # which shrinks every reported Sortino by sqrt(share of losing days).
    closes = [10_000, 10_100, 10_050, 10_200, 9_900, 10_300, 10_350]
    got = summarize(_curve(closes), [], EQ0)["sortino"]
    def sortino(d):
        return d.mean() / math.sqrt(np.mean(np.minimum(d, 0.0) ** 2)) * math.sqrt(365)
    # accept the daily series with or without the (flat) first day, so this test isolates the Sortino formula
    assert got == pytest.approx(sortino(np.diff([EQ0] + closes) / EQ0)) or got == pytest.approx(sortino(np.diff(closes) / EQ0))


# =====================================================================================================
# 6. harness.stitch and harness.monte_carlo
# =====================================================================================================
def test_stitch_chains_fold_pnl_without_gaps_or_double_counting():
    def part(t0, values, n_trades):
        idx = pd.date_range(ts(t0), periods=len(values), freq="h")
        return {"equity": pd.Series(values, index=idx, dtype="float64"), "gross": pd.Series(1.0, index=idx),
                "trades": [{"pnl": 1.0}] * n_trades}
    parts = [part("2025-01-01", [10_000, 10_050, 10_100], 2), part("2025-01-01 03:00", [10_000, 9_900, 9_950], 1),
             part("2025-01-01 06:00", [10_000, 10_000, 10_300], 3)]
    eq, gross, trades = harness.stitch(parts, EQ0)
    assert eq.tolist() == [10_000, 10_050, 10_100, 10_100, 10_000, 10_050, 10_050, 10_050, 10_350]
    assert eq.index.is_monotonic_increasing and eq.index.is_unique and len(gross) == 9 and len(trades) == 6
    s = summarize(eq, [], EQ0)
    assert s["total_return"] == pytest.approx(0.01 - 0.005 + 0.03) and s["max_dd"] == pytest.approx(-0.01)


def _one_trade_per_day(pnl):
    """Trades on separate days, so a fix that keeps same-day trades together changes nothing here."""
    days = pd.date_range(ts("2025-01-01"), periods=len(pnl), freq="D")
    return [{"pnl": float(x), "symbol": "X", "side": 1, "entry_time": (d + pd.Timedelta(hours=1)).isoformat(),
             "exit_time": (d + pd.Timedelta(hours=5)).isoformat()} for x, d in zip(pnl, days)]


def test_monte_carlo_drawdown_counts_from_the_starting_balance():
    lose = harness.monte_carlo(_one_trade_per_day([-10.0] * 20), EQ0)
    assert lose["max_dd_p50"] == pytest.approx(-0.02) and lose["max_dd_p95_worst"] == pytest.approx(-0.02)   # not -0.019
    assert lose["total_return_p50"] == pytest.approx(-0.02) and lose["prob_loss"] == 1.0
    assert lose["p_value_mean_le_0"] == pytest.approx(1.0)
    win = harness.monte_carlo(_one_trade_per_day([10.0] * 20), EQ0)
    assert win["max_dd_p50"] == 0.0 and win["prob_loss"] == 0.0
    assert win["p_value_mean_le_0"] == pytest.approx(1 / (harness.MC_PATHS + 1))                             # never exactly 0
    assert harness.monte_carlo(_one_trade_per_day([10.0] * 9), EQ0)["p_value_mean_le_0"] == 1.0              # < 10 trades


def test_monte_carlo_drawdown_and_totals_match_a_brute_force_bootstrap():
    rng = np.random.default_rng(4)
    pnl = rng.normal(2, 25, 60)
    out = harness.monte_carlo(_one_trade_per_day(pnl), EQ0, seed=3)
    worst, totals = [], []
    for row in np.random.default_rng(99).choice(pnl, size=(20_000, len(pnl)), replace=True):
        level = peak = dd = 0.0
        for x in row:
            level += x
            peak = max(peak, level)                    # the starting balance counts as the first peak
            dd = min(dd, level - peak)
        worst.append(dd / EQ0)
        totals.append(level / EQ0)
    assert out["max_dd_p50"] == pytest.approx(np.percentile(worst, 50), rel=0.05)
    assert out["max_dd_p95_worst"] == pytest.approx(np.percentile(worst, 5), rel=0.05)
    assert out["total_return_p50"] == pytest.approx(np.percentile(totals, 50), abs=0.0015)
    assert out["total_return_p05"] == pytest.approx(np.percentile(totals, 5), abs=0.0015)
    assert out["prob_loss"] == pytest.approx(np.mean(np.array(totals) <= 0), abs=0.02)
    assert out["p_value_mean_le_0"] == pytest.approx(np.mean(np.array(totals) <= 0), abs=0.02)
    assert out["max_dd_p95_worst"] <= out["max_dd_p50"] <= 0.0


def _false_positive_rate(make_trades, reps, monkeypatch):
    monkeypatch.setattr(harness, "MC_PATHS", 400)
    hits = sum(harness.monte_carlo(make_trades(k), EQ0, seed=k)["p_value_mean_le_0"] < 0.05 for k in range(reps))
    return hits / reps


def test_monte_carlo_p_value_is_roughly_calibrated_when_trades_really_are_independent(monkeypatch):
    def make(k):
        return _one_trade_per_day(np.random.default_rng(1000 + k).normal(0, 50, 300))
    assert _false_positive_rate(make, 200, monkeypatch) <= 0.10


def test_monte_carlo_p_value_survives_trades_that_cluster_by_day(monkeypatch):
    # DEFECT: ACC-MC-1
    # A strategy with NO edge whose trades come five to a day and share the day's direction (ten correlated
    # coins break out together). The bootstrap resamples single trades as if they were independent, so it
    # calls this "significant at 5%" about four times as often as it should. On the reference strategy's own
    # validation trades the standard error of the mean trade is 1.76x larger once exit days are kept together.
    def make(k):
        rng = np.random.default_rng(2000 + k)
        days = pd.date_range(ts("2025-01-01"), periods=60, freq="D")
        z = math.sqrt(0.6) * rng.normal(0, 1, (60, 1)) + math.sqrt(0.4) * rng.normal(0, 1, (60, 5))
        return [{"pnl": float(50 * z[d, j]), "symbol": f"S{j}", "side": 1,
                 "entry_time": (days[d] + pd.Timedelta(hours=2)).isoformat(),
                 "exit_time": (days[d] + pd.Timedelta(hours=9 + j)).isoformat()} for d in range(60) for j in range(5)]
    assert _false_positive_rate(make, 200, monkeypatch) <= 0.10          # nominal 0.05; currently about 0.20


# =====================================================================================================
# 7. harness.buy_and_hold
# =====================================================================================================
def _toy_market(monkeypatch, df):
    monkeypatch.setattr(harness.store, "universe", lambda: {"2025-01": [BTC], "2025-02": [BTC]})
    return Market(data={BTC: df}, base=make_base({BTC: df}, slip_bps=3.0))


def _toy_bars(t0, n, price=100.0):
    idx = pd.date_range(ts(t0), periods=n, freq="h", name="time")
    df = pd.DataFrame({"open": price, "high": price, "low": price, "close": price, "funding": 0.0}, index=idx)
    return df


def test_buy_and_hold_charges_funding_every_hour_on_the_position(monkeypatch):
    df = _toy_bars("2025-01-10", 48)
    df["funding"] = 0.0001
    m = _toy_market(monkeypatch, df)
    with_f = harness.buy_and_hold(m, df.index[0], df.index[-1] + pd.Timedelta(hours=1), Costs(), EQ0)["btc"]
    no_f = harness.buy_and_hold(m, df.index[0], df.index[-1] + pd.Timedelta(hours=1), Costs(funding_mult=0.0), EQ0)["btc"]
    # 48 hours at 1x notional. Today the first bar's funding is hidden by the baseline defect (ACC-BH-2): 47 show.
    assert 47 * 0.0001 * 0.998 <= no_f["total_return"] - with_f["total_return"] <= 48 * 0.0001 * 1.002


def test_buy_and_hold_includes_the_cost_of_getting_in(monkeypatch):
    # DEFECT: ACC-BH-2
    # Flat price, no funding: buying and later selling $10k costs taker + slippage on the way in (0.05% + 0.03%)
    # and at least the taker fee on the way out. The harness reports -0.05%: the entry cost is deducted before
    # the first point of the curve and summarize() measures P&L from that first point, so it never shows.
    df = _toy_bars("2025-01-10", 72)
    out = harness.buy_and_hold(_toy_market(monkeypatch, df), df.index[0], df.index[-1] + pd.Timedelta(hours=1), Costs(), EQ0)
    assert out["btc"]["total_return"] <= -0.00125          # -(0.05% + 0.03%) in, -0.05% out; reported: -0.05%


def test_buy_and_hold_earns_the_first_hour_of_each_month(monkeypatch):
    # DEFECT: ACC-BH-1
    # Price is 100 all January, falls to 90 during the FIRST hourly bar of February and stays there.
    # A holder loses 10%. The harness rebases every month on that month's first CLOSE, so the move between
    # the previous month's last close and the new month's first close belongs to neither month and vanishes.
    df = _toy_bars("2025-01-30", 24 * 5)
    feb = df.index >= ts("2025-02-01")
    df.loc[feb, ["low", "close"]] = 90.0
    df.loc[df.index > ts("2025-02-01"), ["open", "high"]] = 90.0
    out = harness.buy_and_hold(_toy_market(monkeypatch, df), df.index[0], df.index[-1] + pd.Timedelta(hours=1), Costs(), EQ0)
    assert out["btc"]["total_return"] == pytest.approx(-0.10, abs=0.003)
    assert out["btc"]["max_dd"] == pytest.approx(-0.10, abs=0.003)


def _independent_basket(raw, market, months_universe, start, end, members_of, base="open", fee=TAKER):
    """Equal dollar legs, rebalanced at each month start, straight from raw bars.

    base="open":  legs are bought at the OPEN of the month's first bar, so every hour's move is earned.
    base="close": the harness convention (first CLOSE), used only to show the rest of its arithmetic agrees."""
    value, w_prev, pieces, first_cost = EQ0, {}, [], None
    for m in pd.period_range(start, end - pd.Timedelta(hours=1), freq="M"):
        a = max(start, m.start_time.tz_localize("UTC"))
        b = min(end, (m + 1).start_time.tz_localize("UTC"))
        hours = pd.date_range(a, b - pd.Timedelta(hours=1), freq="h")
        legs = {s: raw[s].reindex(hours) for s in members_of(str(m))}
        legs = {s: d for s, d in legs.items() if d["close"].notna().sum() >= 2}
        n = len(legs)
        turnover = sum(abs((1 / n if s in legs else 0.0) - w_prev.get(s, 0.0)) for s in set(legs) | set(w_prev))
        slip = np.mean([market.base.arrays[s]["slip_bps"][market.base.index.searchsorted(hours[0])] for s in legs]) / 1e4
        cost = value * turnover * (fee + slip)
        first_cost = cost if first_cost is None else first_cost
        value -= cost
        total, paid, ends = pd.Series(0.0, index=hours), pd.Series(0.0, index=hours), {}
        for s, d in legs.items():
            buy = d["open"].dropna().iloc[0] if base == "open" else d["close"].dropna().iloc[0]
            units = (value / n) / buy
            worth = (units * d["close"].ffill()).fillna(value / n)
            notional_at_open = worth.shift(1).fillna(value / n)
            paid += notional_at_open * d["funding"].fillna(0.0)
            total += worth
            ends[s] = float(worth.iloc[-1])
        curve = total - paid.cumsum()
        pieces.append(curve)
        value = float(curve.iloc[-1])
        w_prev = {s: v / sum(ends.values()) for s, v in ends.items()}
    eq = pd.concat(pieces)
    final = float(eq.iloc[-1]) * (1 - fee)
    return (final - EQ0) / EQ0, first_cost / EQ0


@pytest.fixture(scope="module")
def basket_market():
    from desk.data import store
    uni = store.universe()
    months = ["2025-03", "2025-11", "2025-12", "2026-01"]
    syms = sorted({s for m in months for s in uni[m]} | {BTC})
    market = load_market(end=ts("2026-02-01"), syms=syms)
    raw = {s: store.load(s, end=ts("2026-02-01")) for s in syms}
    return market, raw, uni


@needs_data
@pytest.mark.parametrize("label,a,b", [("btc", "2025-03-01", "2025-04-01"), ("basket", "2025-11-01", "2026-02-01")])
def test_buy_and_hold_arithmetic_matches_raw_bars_apart_from_the_two_known_defects(basket_market, label, a, b):
    market, raw, uni = basket_market
    members = (lambda m: [BTC]) if label == "btc" else (lambda m: [s for s in uni[m] if s in raw])
    got = harness.buy_and_hold(market, ts(a), ts(b), Costs(), EQ0)[label]["total_return"]
    same_convention, first_cost = _independent_basket(raw, market, uni, ts(a), ts(b), members, base="close")
    truth, _ = _independent_basket(raw, market, uni, ts(a), ts(b), members, base="open")
    # Funding, monthly turnover costs, compounding and the final sale agree to a fraction of a basis point once
    # the two known defects are reproduced (month rebased on its first close; entry cost not shown). After they
    # are fixed the harness should simply equal the raw-bar truth.
    assert abs(got - (same_convention + first_cost)) < 1e-4 or abs(got - truth) < 1e-3


@needs_data
@pytest.mark.parametrize("label,a,b", [("btc", "2025-03-01", "2025-04-01"), ("basket", "2025-11-01", "2026-02-01")])
def test_buy_and_hold_matches_an_independent_recomputation_from_raw_bars(basket_market, label, a, b):
    # DEFECT: ACC-BH-1 (and ACC-BH-2)
    # BTC, March 2025: 84,315 at the first open, 82,550 at the last close, 0.64% funding paid, 0.105% costs:
    # -2.85%. The harness says -2.26% because it starts the month at the first close (83,852).
    # Basket, Nov 2025 - Jan 2026: the basket fell 5.6% in the first hour of 1 December; the harness skips it.
    market, raw, uni = basket_market
    members = (lambda m: [BTC]) if label == "btc" else (lambda m: [s for s in uni[m] if s in raw])
    got = harness.buy_and_hold(market, ts(a), ts(b), Costs(), EQ0)[label]["total_return"]
    truth, _ = _independent_basket(raw, market, uni, ts(a), ts(b), members, base="open")
    assert got == pytest.approx(truth, abs=1e-3)


# =====================================================================================================
# 8. scoring.score / scoring.gates against docs/PROTOCOL.md
# =====================================================================================================
def _res(**over):
    v = {"n_trades": 50, "total_return": 0.01, "calmar": 0.5}
    res = {"wf_validation": v, "leak_test": {"passed": True},
           "stress": {"fees_x2": {"total_return": 0.001}, "one_bar_late": {"total_return": 0.001}},
           "neighbourhood": {"share_profitable": 0.60}, "benchmark": {"basket": {"calmar": 0.4}}}
    for k, val in over.items():
        node, keys = res, k.split(".")
        for kk in keys[:-1]:
            node = node[kk]
        node[keys[-1]] = val
    return res


def test_gates_sit_exactly_on_the_protocol_thresholds():
    assert scoring.gates(_res())["all_passed"] is True                       # 50 trades, >0, >0 at 2x fees, 60% grid
    fails = {
        "leak_test.passed": (False, "no_lookahead"),
        "wf_validation.n_trades": (49, "trades_50_plus"),
        "wf_validation.total_return": (0.0, "profit_after_costs"),
        "stress.fees_x2.total_return": (0.0, "profit_fees_doubled"),
        "neighbourhood.share_profitable": (0.59, "nearby_settings_hold"),
        "stress.one_bar_late.total_return": (0.0, "holds_one_bar_late"),     # gate added after the review (N-1)
        "benchmark.basket.calmar": (0.5, "beats_holding"),                   # must BEAT the basket, a tie fails
    }
    for path, (value, gate) in fails.items():
        g = scoring.gates(_res(**{path: value}))
        assert g[gate] is False and g["all_passed"] is False, path
    assert set(scoring.gates(_res())) == {"no_lookahead", "trades_50_plus", "profit_after_costs", "profit_fees_doubled",
                                          "nearby_settings_hold", "holds_one_bar_late", "beats_holding", "all_passed"}


def test_score_bands_are_monotone_and_total_is_out_of_25():
    reg = {"bear": {"annualised": 0.01, "pnl_pct": 0.01}, "chop": {"annualised": 0.01, "pnl_pct": 0.01}}
    def sc(**v):
        return scoring.score({"annual_return": 0.05, "max_dd": -0.08, "n_trades": 150, "longest_losing_streak": 7, **v}, reg)
    assert [sc(annual_return=x)["oos_profit"] for x in (-0.01, 0.0, 0.02, 0.05, 0.10, 0.20)] == [1, 1, 2, 3, 4, 5]
    assert [sc(max_dd=x)["max_drawdown"] for x in (-0.20, -0.12, -0.08, -0.04, -0.02)] == [1, 2, 3, 4, 5]
    assert [sc(n_trades=x)["trade_count"] for x in (49, 50, 100, 200, 400)] == [1, 2, 3, 4, 5]
    assert [sc(longest_losing_streak=x)["losing_streak"] for x in (12, 11, 8, 6, 4)] == [1, 2, 3, 4, 5]
    best = sc(annual_return=0.2, max_dd=-0.01, n_trades=500, longest_losing_streak=2)
    assert best["bear_chop"] == 5 and best["total"] == 25


@needs_data
def test_bear_chop_score_uses_only_the_validation_quarters():
    # DEFECT: ACC-SC-1
    # PROTOCOL: "Ranking uses only the quarters inside VALIDATION." The bear/chop score is fed the regime
    # table of the WHOLE walk-forward (from 2023-10), so results earned in the DESIGN window move it.
    # This test double trades (with hindsight, so it wins) only before 2025 and is silent in VALIDATION:
    # zero validation trades, zero validation P&L, yet it is awarded 5/5 for surviving bear and chop.
    from desk.data import store
    from desk.strategies.base import Strategy

    class OnlyBefore2025(Strategy):
        name, params, grid, max_hold = "probe_only_before_2025", {"k": 1}, {"k": [1]}, 24

        def intents(self, data, p):
            out = {}
            for s, df in data.items():
                it = blank_intents(df.index)
                fwd = df["close"].shift(-24) / df["close"] - 1               # hindsight on purpose (test double)
                on = (fwd > 0.02) & (df.index < store.DESIGN_END - pd.Timedelta(days=3)) & (df.index.hour == 0)
                it["side"] = np.where(on, 1, 0).astype(np.int8)
                it["stop"] = df["close"] * 0.9
                out[s] = it
            return out

    market = load_market(end=store.VALIDATION_END, syms=[BTC])
    res = harness.audit(OnlyBefore2025(), market)
    assert res["wf_validation"]["n_trades"] == 0 and res["wf_validation"]["total_return"] == 0.0
    eq = res["_equity_all"]
    eq_val = eq[eq.index >= store.DESIGN_END]
    eq_val = eq_val - eq_val.iloc[0] + EQ0                                   # the validation quarters on their own
    validation_only = harness.by_regime(eq_val, harness.btc_regimes(market)["trend"], EQ0)
    assert all(v["pnl_pct"] == 0.0 for v in validation_only.values())
    assert res["scores"]["bear_chop"] == scoring.score(res["wf_validation"], validation_only)["bear_chop"]
