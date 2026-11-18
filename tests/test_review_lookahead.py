"""Adversarial review, lens = LOOK-AHEAD AND TIMING.

Tests marked  # DEFECT: <id>  FAIL on the code as reviewed and should pass once the
defect is fixed. Everything else passes and pins down behaviour that was verified.

All data here is synthetic (random walks on an hourly UTC index), so nothing touches
the sealed holdout. Real-data numbers quoted in the review come from the scripts in
research/review/lookahead/.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from desk.audit import harness, scoring
from desk.audit.harness import leak_test
from desk.data import store
from desk.data.store import BTC, DESIGN_END, VALIDATION_END
from desk.engine.core import Costs, Engine, Risk, attach, blank_intents, build_feed, make_base
from desk.engine.costs import slip_series
from desk.engine.runner import Market, run_feed
from desk.strategies import ta
from desk.strategies.base import Strategy
from desk.strategies.ref_donchian import RefDonchian

UTC = "UTC"


# --------------------------------------------------------------------------- data
def synth(n_sym: int = 6, n: int = 9000, seed: int = 1, start: str = "2023-01-01") -> dict[str, pd.DataFrame]:
    """Fat-tailed random walks with slow volatility regimes. Symbol 0 is BTC."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="h", tz=UTC, name="time")
    out = {}
    for k in range(n_sym):
        vol = 0.006 * np.exp(0.6 * np.sin(np.arange(n) / 700.0 + k))
        r = rng.standard_t(4, n) * vol / np.sqrt(2.0)
        close = 100.0 * (k + 1) * np.exp(np.cumsum(r))
        op = np.r_[close[0], close[:-1]]                      # like the venue: open == previous close
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.0015, n)))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.0015, n)))
        df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close}, index=idx)
        df["volume"] = rng.lognormal(10, 1, n)
        df["funding"] = rng.normal(0, 1e-5, n)
        df["bar_missing"] = False
        out[BTC if k == 0 else f"PF_S{k}USD"] = df
    return out


@pytest.fixture(scope="module")
def data():
    return synth()


class _Base(Strategy):
    """Per-symbol helper: subclasses fill one intents frame."""
    name = "review"
    params: dict = {}
    grid: dict = {}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            self.fill(it, df, p, data, s)
            out[s] = it
        return out

    def fill(self, it, df, p, data, sym):   # pragma: no cover
        raise NotImplementedError


def _breakout(df: pd.DataFrame, n: int = 48) -> pd.Series:
    """A causal entry signal used by the 'leak only in one column' strategies."""
    return (df["close"] > ta.donchian_high(df, n)).fillna(False)


# ------------------------------------------------------------ leaky strategies
class PeekNextBar(_Base):
    """Perfect foresight: buy at the close of t when bar t+1 will close up > thr."""
    name = "peek_next_bar"
    params = {"thr": 0.02}

    def fill(self, it, df, p, data, sym):
        nxt = df["close"].shift(-1) / df["close"] - 1.0          # <- the future
        sig = (nxt > p["thr"]).fillna(False)
        it["side"] = sig.astype(np.int8)
        it["stop"] = df["close"] * 0.97
        it["exit"] = sig.shift(1, fill_value=False).to_numpy(dtype=bool)   # out one bar later


class CentredDense(_Base):
    """Mean reversion to a CENTRED moving average, signalling on a large share of bars."""
    name = "centred_dense"

    def fill(self, it, df, p, data, sym):
        ma = df["close"].rolling(25, center=True, min_periods=1).mean()   # <- 12 bars of future
        it["side"] = (df["close"] < ma * 0.998).astype(np.int8)
        it["stop"] = df["close"] * 0.97


class WholeSampleQuantile(_Base):
    """Volume-spike breakout where 'spike' is a WHOLE-SAMPLE quantile."""
    name = "whole_sample_quantile"

    def fill(self, it, df, p, data, sym):
        thr = df["volume"].quantile(0.99)                         # <- fitted on the full series
        sig = (df["volume"] > thr) & (df["close"] > df["open"])
        it["side"] = sig.astype(np.int8)
        it["stop"] = df["close"] * 0.97


class SparseLeak(_Base):
    """Causal breakout, plus a peek on ONE bar a week (Monday 00:00 UTC)."""
    name = "sparse_leak"

    def fill(self, it, df, p, data, sym):
        monday0 = (df.index.dayofweek == 0) & (df.index.hour == 0)
        peek = (df["close"].shift(-1) > df["close"] * 1.004).fillna(False) & monday0   # <- future, 1 bar in 168
        it["side"] = (_breakout(df, 96) | peek).astype(np.int8)
        it["stop"] = df["close"] * 0.97


class CrossSymbolLeak(_Base):
    """Alts are bought when BTC's NEXT bar is going to be strong."""
    name = "cross_symbol_leak"

    def fill(self, it, df, p, data, sym):
        b = data[BTC]["close"]
        nxt = (b.shift(-1) / b - 1.0).reindex(df.index)           # <- another symbol's future
        sig = (nxt > 0.015).fillna(False) & (sym != BTC)
        it["side"] = sig.astype(np.int8)
        it["stop"] = df["close"] * 0.97


class StopOnlyLeak(_Base):
    """Causal entry; only the STOP peeks (parked just under the next bar's low)."""
    name = "stop_only_leak"

    def fill(self, it, df, p, data, sym):
        it["side"] = _breakout(df).astype(np.int8)
        it["stop"] = np.minimum(df["low"].shift(-1), df["close"]) * 0.997   # <- future low


class LimitOnlyLeak(_Base):
    """Causal entry; only the LIMIT peeks (bid placed just above the next bar's low)."""
    name = "limit_only_leak"

    def fill(self, it, df, p, data, sym):
        it["side"] = _breakout(df).astype(np.int8)
        it["limit"] = df["low"].shift(-1) * 1.0005                # <- future low
        it["stop"] = df["close"] * 0.95


class TrailOnlyLeak(_Base):
    """Causal entry and stop; TRAIL is tightened only on bars followed by a drop."""
    name = "trail_only_leak"

    def fill(self, it, df, p, data, sym):
        it["side"] = _breakout(df).astype(np.int8)
        it["stop"] = df["close"] * 0.95
        drop_next = df["low"].shift(-1) < df["close"] * 0.985     # <- future low
        it["trail"] = (df["close"] * 0.999).where(drop_next)


class ExitOnlyLeak(_Base):
    """Causal entry and stop; EXIT fires only on bars followed by a fall."""
    name = "exit_only_leak"

    def fill(self, it, df, p, data, sym):
        it["side"] = _breakout(df).astype(np.int8)
        it["stop"] = df["close"] * 0.95
        it["exit"] = (df["close"].shift(-1) < df["close"] * 0.985).fillna(False).to_numpy(dtype=bool)   # <- future


class Resample4hLeak(_Base):
    """4-hour bars stamped at their OPEN and forward-filled onto the hourly rows:
    the 00:00 hourly row already carries the 4h close printed at 04:00."""
    name = "resample_4h_leak"

    def fill(self, it, df, p, data, sym):
        c4 = df["close"].resample("4h").last()
        up = (c4 / c4.shift(1) - 1.0) > 0.02                      # this 4h bar closes up > 2%
        sig = up.reindex(df.index, method="ffill").fillna(False) & (df.index.hour % 4 == 0)   # <- 3 bars of future
        it["side"] = sig.astype(np.int8)
        it["stop"] = df["close"] * 0.97


class GridOnlyLeak(_Base):
    """Causal with the default parameters; one grid cell uses the next bar."""
    name = "grid_only_leak"
    params = {"confirm": 0}
    grid = {"confirm": [0, 1]}

    def fill(self, it, df, p, data, sym):
        sig = _breakout(df)
        if p["confirm"]:
            sig = sig & (df["close"].shift(-1) > df["close"]).fillna(False)   # <- 'confirmed by the next bar'
        it["side"] = sig.astype(np.int8)
        it["stop"] = df["close"] * 0.97


class CachedLeak(CentredDense):
    """The dense centred-window leak again, with an innocent-looking per-symbol
    indicator cache (added 'to make the 36-cell grid fast')."""
    name = "cached_leak"

    def __init__(self):
        self._cache: dict[str, pd.Series] = {}

    def fill(self, it, df, p, data, sym):
        if sym not in self._cache:
            self._cache[sym] = df["close"].rolling(25, center=True, min_periods=1).mean()
        ma = self._cache[sym].reindex(df.index)
        it["side"] = (df["close"] < ma * 0.998).astype(np.int8)
        it["stop"] = df["close"] * 0.97


class ReadsStoreDirectly(_Base):
    """Ignores the frames it is handed and loads the bars itself with store.load(sym),
    i.e. the complete file on disk -- which contains the sealed holdout."""
    name = "reads_store_directly"

    def fill(self, it, df, p, data, sym):
        c = store.load(sym)["close"]                              # <- not the argument
        nxt = (c.shift(-1) / c - 1.0).reindex(df.index)
        it["side"] = (nxt > 0.004).fillna(False).astype(np.int8)
        it["stop"] = df["close"] * 0.97


def _truly_leaky(strategy, data, params=None, n_probe: int = 60) -> bool:
    """Ground truth by brute force: put a truncation right after `n_probe` rows that
    actually act (side / exit / trail) and see whether the row is reproduced. Slow but
    decisive; this is the 'targeted cut' the review proposes for harness.leak_test."""
    p = dict(strategy.params if params is None else params)
    full = strategy.intents(data, p)
    acts = []
    for s, f in full.items():
        m = (f["side"].to_numpy() != 0) | f["exit"].to_numpy(dtype=bool) | f["trail"].notna().to_numpy()
        acts += [(t, s) for t in f.index[m]]
    if not acts:
        return False
    rng = np.random.default_rng(123)
    for k in rng.choice(len(acts), size=min(n_probe, len(acts)), replace=False):
        t, s = acts[int(k)]
        part = {x: df[df.index <= t] for x, df in data.items()}
        part = {x: df for x, df in part.items() if len(df)}
        got = strategy.intents(part, p)[s].iloc[-1]
        want = full[s].loc[t]
        for col in ("side", "limit", "stop", "tp", "trail", "exit"):
            a, b = float(got[col]), float(want[col])
            if not ((np.isnan(a) and np.isnan(b)) or np.isclose(a, b, rtol=1e-9, atol=1e-12)):
                return True
    return False


# ================================================================ leak_test: verified
SEEDS = range(12)     # harness.audit always uses seed 0; a gate must not depend on which five instants it drew


def _missed_seeds(strategy, data) -> list[int]:
    return [k for k in SEEDS if leak_test(strategy, data, seed=k)["passed"]]


def test_leak_test_passes_causal_reference(data):
    assert _missed_seeds(RefDonchian(), data) == list(SEEDS)
    assert not _truly_leaky(RefDonchian(), data)


def test_leak_test_catches_a_dense_centred_window(data):
    """It does work when the leak moves a signal on a large share of bars."""
    assert _missed_seeds(CentredDense(), data) == []


LEAKY = [PeekNextBar, WholeSampleQuantile, SparseLeak, CrossSymbolLeak, StopOnlyLeak, LimitOnlyLeak, TrailOnlyLeak,
         ExitOnlyLeak, Resample4hLeak]


@pytest.mark.parametrize("cls", LEAKY, ids=lambda c: c.name)
def test_each_leaky_strategy_really_is_leaky(cls, data):
    """Guards the DEFECT tests below against a false premise (brute-force ground truth)."""
    assert _truly_leaky(cls(), data, n_probe=150)


# ================================================================= leak_test: defects
@pytest.mark.parametrize("cls", LEAKY, ids=lambda c: c.name)
def test_leak_test_must_catch_the_leak_whatever_the_seed(cls, data):
    # DEFECT: LA-1  five cuts, only the last 48 rows, stop/limit/tp only on signal rows: a short peek is visible
    #               only if a signal happens to sit on the last bar or two before one of five instants
    assert _missed_seeds(cls(), data) == []


def test_leak_test_default_seed_misses_these_on_the_same_bars_every_night(data):
    # DEFECT: LA-1  (what the audit as shipped, seed=0, lets through on this dataset)
    passed = [c.name for c in LEAKY if leak_test(c(), data)["passed"]]
    assert passed == []


def test_leak_test_must_cover_every_grid_cell_not_just_the_defaults(data):
    # DEFECT: LA-2  (walk-forward trades any cell; only strategy.params is truncation-tested)
    s = GridOnlyLeak()
    assert {"confirm": 1} in harness.grid_cells(s)       # the audit WILL trade this cell
    assert _truly_leaky(s, data, {"confirm": 1}) and not _truly_leaky(s, data, {"confirm": 0})
    assert not leak_test(s, data)["passed"]


def test_leak_test_must_not_be_fooled_by_a_per_symbol_cache(data):
    # DEFECT: LA-3  (audit() computes every cell's intents BEFORE leak_test, so any cache is already warm
    #                with full-history values; the 'truncated' runs then return the cached full-history numbers)
    s = CachedLeak()
    s.intents(data, dict(s.params))                      # what audit() does first
    assert not leak_test(s, data)["passed"]


def test_leak_test_must_notice_a_strategy_that_reads_the_store_itself(data, monkeypatch):
    # DEFECT: LA-3  (truncating the ARGUMENT proves nothing when the bars come from store.load, which serves
    #                the whole file including the holdout; nothing stops or detects that today)
    monkeypatch.setattr(store, "_read", lambda sym: data[sym])
    assert not leak_test(ReadsStoreDirectly(), data)["passed"]


def test_leak_test_cuts_never_probe_the_first_third_of_history(data):
    # DEFECT: LA-4  (cuts are drawn from 35%..98% of the span, and only the 48 rows before each are compared)
    class EarlyOnly(_Base):
        name = "early_only"

        def fill(self, it, df, p, data, sym):
            early = df.index < df.index[0] + pd.Timedelta(hours=2500)      # first 28% of this sample
            nxt = (df["close"].shift(-1) > df["close"] * 1.002).fillna(False)   # <- future
            it["side"] = (nxt & early).astype(np.int8)
            it["stop"] = df["close"] * 0.97

    assert _truly_leaky(EarlyOnly(), data)
    assert _missed_seeds(EarlyOnly(), data) == []


# ========================================================== reference hardened test
def hardened_leak_test(strategy, data, n_random: int = 4, n_targeted: int = 40, seed: int = 0, fresh=None) -> dict:
    """PROPOSAL for harness.leak_test: same contract, roughly 8x the intents calls per cell.

    1. every grid cell, not only the defaults;
    2. cuts placed right AFTER rows that act (side / exit / trail), sampled over the whole
       history, plus a few random cuts from 5% of the span onward;
    3. every row of the truncated output is compared, not the last 48;
    4. each probe runs on a FRESH strategy instance (in the harness: importlib.reload of the
       strategy module), and the reference is the intents object that is actually traded;
    5. purity control: handing two symbols each other's frames must swap their outputs. A
       strategy that keys anything on the symbol name outside its argument (cache, disk
       read) fails it.

    Sampling cannot promise to find a leak that touches 1 signal in 50; for that, replay
    every reported trade's signal row (n_targeted=None) before a finalist sees the holdout.
    """
    rng = np.random.default_rng(seed)
    fresh = fresh or (lambda: type(strategy)())
    lo = min(df.index[0] for df in data.values())
    hi = max(df.index[-1] for df in data.values())
    mism, examples, probes, impure = 0, [], 0, []

    def diff(g: pd.DataFrame, f: pd.DataFrame) -> int:
        f = f.reindex(g.index)
        acting = (g["side"].to_numpy(dtype="float64") != 0) | (f["side"].to_numpy(dtype="float64") != 0)
        n = 0
        for col in ("side", "limit", "stop", "tp", "trail", "exit"):
            a, b = g[col].to_numpy(dtype="float64"), f[col].to_numpy(dtype="float64")
            bad = ~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))
            if col in ("limit", "stop", "tp"):
                bad &= acting
            n += int(bad.sum())
        return n

    for cell in harness.grid_cells(strategy):
        full = strategy.intents(data, dict(cell))            # in the harness: the object handed to attach()
        acts = sorted({t for f in full.values() for t in f.index[
            (f["side"].to_numpy() != 0) | f["exit"].to_numpy(dtype=bool) | f["trail"].notna().to_numpy()]})
        cuts = [(lo + (hi - lo) * float(rng.uniform(0.05, 0.99))).floor("h") for _ in range(n_random)]
        if acts:
            k = len(acts) if n_targeted is None else min(n_targeted, len(acts))
            cuts += [acts[int(i)] + pd.Timedelta(hours=1) for i in rng.choice(len(acts), size=k, replace=False)]
        for cut in cuts:
            part = {s: df[df.index < cut] for s, df in data.items()}
            got = fresh().intents({s: df for s, df in part.items() if len(df)}, dict(cell))
            probes += 1
            for s, g in got.items():
                d = diff(g, full[s])
                if d:
                    mism += d
                    if len(examples) < 5:
                        examples.append({"symbol": s, "cut": cut.isoformat(), "cell": cell})
        others = [s for s in data if s != BTC]
        if len(others) >= 2:
            a, b = others[0], others[1]
            got = fresh().intents({**data, a: data[b], b: data[a]}, dict(cell))
            if diff(got[a], full[b]) or diff(got[b], full[a]):
                impure.append(cell)
    return {"passed": mism == 0 and not impure, "mismatches": mism, "probes": probes,
            "not_a_function_of_its_input": impure, "examples": examples}


def test_proposed_hardening_keeps_causal_code_clean(data):
    assert hardened_leak_test(RefDonchian(), data, n_targeted=12)["passed"]     # 9 cells x 17 probes
    assert hardened_leak_test(_TwoCell(), data)["passed"]


@pytest.mark.parametrize("cls", [PeekNextBar, CentredDense, WholeSampleQuantile, CrossSymbolLeak, StopOnlyLeak,
                                 LimitOnlyLeak, TrailOnlyLeak, ExitOnlyLeak, Resample4hLeak, GridOnlyLeak],
                         ids=lambda c: c.name)
def test_proposed_hardening_catches(cls, data):
    for seed in range(2):
        assert not hardened_leak_test(cls(), data, seed=seed)["passed"]


def test_proposed_hardening_catches_state_and_outside_reads(data, monkeypatch):
    warm = CachedLeak()
    warm.intents(data, dict(warm.params))
    assert not hardened_leak_test(warm, data)["passed"]                       # fresh instance per probe
    monkeypatch.setattr(store, "_read", lambda sym: data[sym])
    r = hardened_leak_test(ReadsStoreDirectly(), data)
    assert not r["passed"] and r["not_a_function_of_its_input"]              # swap control


def test_a_leak_on_a_few_bars_needs_exhaustive_replay_not_sampling():
    """One peeking bar a week drives about 3% of this strategy's signals. Forty sampled cuts
    find it less than half the time; replaying every acting row always does. Budget: one
    intents() call per distinct signal bar, so reserve it for finalists."""
    small = synth(n_sym=2, n=2500, seed=2)
    s = SparseLeak()
    assert _truly_leaky(s, small, n_probe=10_000)
    assert not hardened_leak_test(s, small, n_targeted=None)["passed"]


# ====================================================================== engine timing
T0 = pd.Timestamp("2024-01-01", tz=UTC)


def _bars(rows, funding=0.0, start=T0):
    idx = pd.date_range(start, periods=len(rows), freq="h", name="time")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype="float64")
    df["funding"] = funding
    return df


def _run(df, it, **kw):
    feed = build_feed({"X": df}, {"X": it}, slip_bps=0.0)
    eng = Engine(Costs(taker_fee=0.0, maker_fee=0.0), Risk(guardian=False), **kw)
    eng.run(feed)
    return eng


def test_limit_intent_cannot_fill_on_its_own_bar_even_if_that_bar_traded_through_it():
    df = _bars([[100, 101, 90, 100], [100, 101, 99.5, 100], [100, 101, 99.5, 100]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "limit", "stop"]] = [1, 95.0, 85.0]      # bar 0's own low is 90 < 95
    eng = _run(df, it, valid_bars=2)
    assert not eng.state.positions and not eng.trades


def test_trail_set_at_bar_t_cannot_stop_the_position_inside_bar_t():
    # long from bar 1; at bar 2 the trail is raised ABOVE bar 2's own low. It may only act from bar 3.
    df = _bars([[100, 100, 100, 100], [100, 101, 99.5, 100], [100, 106, 99, 105], [105, 106, 104.5, 105.5],
                [105.5, 106, 102, 103]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    it.loc[df.index[2], "trail"] = 103.0
    eng = _run(df, it)
    assert len(eng.trades) == 1
    t = eng.trades[0]
    assert t["reason"] == "stop" and t["exit_time"] == df.index[4].isoformat() and t["exit_price"] == 103.0


def test_exit_intent_fills_at_next_open_not_at_the_signal_close():
    df = _bars([[100, 100, 100, 100], [100, 101, 99.5, 100], [100, 120, 99.5, 120], [110, 111, 109, 110]])
    it = blank_intents(df.index)
    it.loc[df.index[0], ["side", "stop"]] = [1, 95.0]
    it.loc[df.index[2], "exit"] = True
    eng = _run(df, it)
    assert eng.trades[0]["exit_price"] == 110.0 and eng.trades[0]["exit_time"] == df.index[3].isoformat()


def test_changing_bars_after_i_does_not_change_anything_up_to_i():
    """Engine state after bar i is a function of bars and intents <= i only."""
    d = synth(n_sym=2, n=1500, seed=5)
    strat = RefDonchian()
    it = strat.intents(d, dict(strat.params))
    cut = 900
    d2 = {s: df.copy() for s, df in d.items()}
    for df in d2.values():
        df.iloc[cut:, :4] = df.iloc[cut:, :4].to_numpy() * 3.0
    it2 = {s: f.copy() for s, f in it.items()}
    for f in it2.values():
        f.iloc[cut:, f.columns.get_loc("side")] = 0
    a, b = Engine(Costs(), Risk()), Engine(Costs(), Risk())
    a.run(build_feed(d, it, slip_bps=3.0), 0, cut)
    b.run(build_feed(d2, it2, slip_bps=3.0), 0, cut)
    assert len(a.trades) > 3 and a.trades == b.trades
    assert a.state.to_json() == b.state.to_json()
    assert np.array_equal(a.equity_curve[:cut], b.equity_curve[:cut], equal_nan=True)


def test_run_feed_window_reads_nothing_at_or_after_end_and_starts_flat():
    d = synth(n_sym=2, n=1500, seed=6)
    strat = RefDonchian()
    it = strat.intents(d, dict(strat.params))
    idx = next(iter(d.values())).index
    t0, t1 = idx[500], idx[1000]
    d2 = {s: df.copy() for s, df in d.items()}
    for df in d2.values():
        df.loc[df.index >= t1, ["open", "high", "low", "close"]] *= 0.2
    r1 = run_feed(build_feed(d, it, slip_bps=3.0), strat, t0, t1)
    r2 = run_feed(build_feed(d2, it, slip_bps=3.0), strat, t0, t1)
    assert r1["trades"] == r2["trades"] and len(r1["trades"]) > 2
    assert r1["equity"].equals(r2["equity"])
    assert min(pd.Timestamp(t["entry_time"]) for t in r1["trades"]) > t0      # an order needs a bar inside the window
    assert max(pd.Timestamp(t["exit_time"]) for t in r1["trades"]) < t1


def test_one_bar_late_stress_really_delays_every_column_by_exactly_one_bar():
    df = _bars([[100 + i, 101 + i, 99 + i, 100 + i] for i in range(8)])
    it = blank_intents(df.index)
    it.loc[df.index[1], ["side", "stop", "tp"]] = [1, 90.0, 150.0]
    it.loc[df.index[3], "trail"] = 95.0
    it.loc[df.index[5], "exit"] = True
    base = make_base({"X": df}, slip_bps=0.0)
    now = attach(base, {"X": it}).sym["X"]
    late = attach(base, {"X": it.shift(1)}).sym["X"]              # exactly what harness.audit does
    assert late.side.tolist() == [0] + now.side.tolist()[:-1]
    assert late.exit.tolist() == [False] + now.exit.tolist()[:-1]
    for col in ("stop", "tp", "trail", "limit"):
        assert np.array_equal(getattr(late, col)[1:], getattr(now, col)[:-1], equal_nan=True)
    e_now, e_late = Engine(Costs(0, 0), Risk(guardian=False)), Engine(Costs(0, 0), Risk(guardian=False))
    e_now.run(attach(base, {"X": it}))
    e_late.run(attach(base, {"X": it.shift(1)}))
    assert e_now.trades[0]["entry_time"] == df.index[2].isoformat()
    assert e_late.trades[0]["entry_time"] == df.index[3].isoformat()
    assert e_late.trades[0]["exit_time"] == df.index[7].isoformat()


def test_one_bar_late_exposes_a_one_bar_peek_but_no_gate_reads_it(data):
    """The stress is the cheapest look-ahead alarm in the audit: a 1-bar peek turns from a
    money machine into a loser. It is informational only (see the 'note' in the review)."""
    s = PeekNextBar()
    it = s.intents(data, dict(s.params))
    base = make_base(data, slip_bps=3.0)
    risk = Risk(guardian=False)
    now = run_feed(attach(base, it), s, risk=risk)["summary"]
    late = run_feed(attach(base, {k: v.shift(1) for k, v in it.items()}), s, risk=risk)["summary"]
    assert now["n_trades"] > 50 and now["win_rate"] > 0.95 and now["total_return"] > 0.5
    assert late["total_return"] < 0.1 * now["total_return"]
    res = {"leak_test": {"passed": True}, "wf_validation": {"n_trades": 99, "total_return": 1.0, "calmar": 9.0},
           "stress": {"fees_x2": {"total_return": 1.0}, "one_bar_late": {"total_return": -1.0}},
           "neighbourhood": {"share_profitable": 1.0}, "benchmark": {"basket": {"calmar": 0.1}}}
    g = scoring.gates(res)                             # the gap this test documented is closed: the gate added after
    assert g["holds_one_bar_late"] is False and g["all_passed"] is False     # the review (N-1) now fails it


# =============================================================== universe / tradable
def test_tradable_mask_uses_the_bar_open_month_and_the_stored_universe():
    uni = store.universe()
    month = sorted(uni)[10]
    nxt = (pd.Timestamp(month + "-01", tz=UTC) + pd.DateOffset(months=1))
    sym = uni[month][0]
    idx = pd.date_range(nxt - pd.Timedelta(hours=2), periods=4, freq="h", tz=UTC)
    m = store.tradable_mask(sym, idx)
    assert m.iloc[0] and m.iloc[1]
    assert bool(m.iloc[2]) == (sym in uni[nxt.strftime("%Y-%m")])


def test_universe_file_is_reproducible_from_strictly_earlier_daily_candles():
    """Point-in-time check on the shipped data/universe.json: month m is ranked on daily
    candles stamped < m (daily stamps are day-OPEN times; verified against hourly sums)."""
    p = store.DATA / "daily_volume.parquet"
    if not p.exists():
        pytest.skip("daily_volume.parquet not present")
    daily = pd.read_parquet(p)
    dv = daily.pivot(index="time", columns="symbol", values="dollar_vol")
    for m, stored in store.universe().items():
        mt = pd.Timestamp(m + "-01", tz=UTC)
        win = dv[(dv.index >= mt - pd.Timedelta(days=30)) & (dv.index < mt)]
        med = win.fillna(0).median()[(win > 0).sum() >= 20].sort_values(ascending=False)
        ranked = [s for s in med.index if s in stored]
        assert ranked == stored, m                              # same order as the prior-30-day ranking
        cutoff = med[stored[-1]]
        outranked_by = [s for s in med.index if med[s] > cutoff and s not in stored]
        assert all("XAUT" in s for s in outranked_by), (m, outranked_by)   # only excluded non-crypto ranks above


def test_entry_must_not_fill_in_a_month_the_symbol_is_outside_the_universe():
    # DEFECT: LA-6  (membership is checked on the SIGNAL bar; the fill is one bar later, possibly next month)
    start = pd.Timestamp("2024-01-31 21:00", tz=UTC)
    df = _bars([[100, 101, 99, 100]] * 8, start=start)
    it = blank_intents(df.index)
    it.loc[pd.Timestamp("2024-01-31 23:00", tz=UTC), ["side", "stop"]] = [1, 90.0]
    tradable = pd.Series(df.index < pd.Timestamp("2024-02-01", tz=UTC), index=df.index)    # in the set in January only
    feed = build_feed({"X": df}, {"X": it}, tradable={"X": tradable}, slip_bps=0.0)
    eng = Engine(Costs(0, 0), Risk(guardian=False))
    eng.run(feed)
    opened = [p.entry_time for p in eng.state.positions.values()] + [t["entry_time"] for t in eng.trades]
    assert all(pd.Timestamp(t) < pd.Timestamp("2024-02-01", tz=UTC) for t in opened), opened


# ============================================================================ costs
def _depth_frame(n=24 * 400, seed=3, depth_from=24 * 60):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz=UTC, name="time")
    mid = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    half = 0.0004 * np.exp(rng.normal(0, 0.5, n)) * (1 + 3 * (np.arange(n) < depth_from + 24 * 30))  # wide early
    df = pd.DataFrame({"close": mid, "bid_10k": mid * (1 - half), "ask_10k": mid * (1 + half)}, index=idx)
    df.loc[df.index[:depth_from], ["bid_10k", "ask_10k"]] = np.nan
    return df


def test_slippage_after_the_estimated_era_is_causal_and_lagged_one_bar():
    df = _depth_frame()
    full = slip_series(df)
    first = df["bid_10k"].first_valid_index()
    for k in (24 * 250, 24 * 300, 24 * 399):
        part = slip_series(df.iloc[:k])
        live = part.index >= first + pd.Timedelta(days=181)
        assert np.allclose(part[live], full.reindex(part.index)[live])
    # lag: a spread explosion in bar t must not change the cost charged in bar t
    t = 24 * 350
    d2 = df.copy()
    d2.iloc[t, d2.columns.get_loc("ask_10k")] *= 1.05
    assert slip_series(d2).iloc[t] == full.iloc[t]


def test_slippage_charged_before_depth_history_starts_must_not_depend_on_later_depth():
    # DEFECT: LA-7  (the pre-history estimate is the median of the NEXT 180 measured days x 1.5)
    df = _depth_frame()
    first = df["bid_10k"].first_valid_index()
    t = df.index[100]                                             # 50+ days before any depth was published
    assert t < first
    d2 = df.copy()
    later = d2.index >= first + pd.Timedelta(days=40)             # the book changes long AFTER t
    mid = (d2["ask_10k"] + d2["bid_10k"]) / 2
    d2.loc[later, "ask_10k"] = mid[later] * 1.01
    d2.loc[later, "bid_10k"] = mid[later] * 0.99
    assert slip_series(d2)[t] == pytest.approx(slip_series(df)[t])


def test_funding_backfill_must_not_be_fitted_on_rows_inside_the_sealed_holdout():
    # DEFECT: LA-8  (fit_funding regresses on every actual rate the venue serves: 2025-11-17 .. download day.
    #                Half of those rows are HOLDOUT; the fitted a, k then write `funding` for every earlier bar)
    from desk.data.download import fit_funding

    def build(k_in_holdout: float) -> pd.Series:
        rng = np.random.default_rng(0)
        idx = pd.date_range("2025-06-01", "2026-10-01", freq="h", tz=UTC, name="time")
        prem = pd.Series(rng.normal(2e-4, 4e-4, len(idx)), index=idx)
        k = np.where(idx < VALIDATION_END, 0.04, k_in_holdout)
        actual = pd.Series(k * prem.shift(1).to_numpy(), index=idx)
        actual[idx < pd.Timestamp("2025-11-17", tz=UTC)] = np.nan          # the venue serves ~1 year only
        df = pd.DataFrame({"premium": prem, "funding_actual": actual})
        for c in ("oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol"):
            df[c] = 0.0
        fit_funding({"PF_XBTUSD": df})
        return df.loc[df["funding_is_est"], "funding"]

    same, different = build(0.04), build(0.07)      # identical before the holdout, different only inside it
    assert len(same) > 3000
    assert np.allclose(same.to_numpy(), different.to_numpy(), rtol=1e-6, atol=1e-12)


# ========================================================================== regimes
def _btc_market(n_days=900, seed=4):
    n = n_days * 24
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz=UTC, name="time")
    c = 30000 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    return pd.DataFrame({"open": np.r_[c[0], c[:-1]], "high": c * 1.001, "low": c * 0.999, "close": c,
                         "funding": 0.0}, index=idx)


def test_btc_regime_labels_are_causal_and_known_at_the_start_of_the_day():
    df = _btc_market()
    full = harness.btc_regimes(Market(data={BTC: df}, base=None))
    for cut in (24 * 500 + 7, 24 * 700, 24 * 860 + 23):
        part = harness.btc_regimes(Market(data={BTC: df.iloc[:cut]}, base=None))
        assert part.equals(full.loc[part.index])                  # truncation-invariant, partial last day included
    # label of day D uses nothing from day D: wrecking day D's prices leaves label[D] alone
    day = full.index[600]
    d2 = df.copy()
    d2.loc[(d2.index >= day) & (d2.index < day + pd.Timedelta(days=1)), "close"] *= 0.5
    assert harness.btc_regimes(Market(data={BTC: d2}, base=None)).loc[day].equals(full.loc[day])


def test_by_regime_attributes_a_days_pnl_to_the_label_known_that_morning():
    days = pd.date_range("2024-01-01", periods=4, freq="D", tz=UTC)
    eq = pd.Series([100.0, 100.0, 110.0, 110.0, 110.0, 90.0],
                   index=[days[0], days[0] + pd.Timedelta(hours=23), days[1] + pd.Timedelta(hours=5),
                          days[1] + pd.Timedelta(hours=23), days[2], days[2] + pd.Timedelta(hours=23)])
    labels = pd.Series(["chop", "bull", "bear", "chop"], index=days)
    out = harness.by_regime(eq, labels, 100.0)
    assert out["bull"]["pnl_pct"] == pytest.approx(0.10) and out["bear"]["pnl_pct"] == pytest.approx(-0.20)


# ====================================================================== walk-forward
def test_folds_train_strictly_before_test_and_tile_the_period():
    f = harness.folds()
    assert f[0][1] == harness.WF_START and f[-1][2] == VALIDATION_END
    for (tr0, t0, t1), nxt in zip(f, f[1:] + [None]):
        assert tr0 < t0 < t1 and tr0 == t0 - pd.DateOffset(months=harness.TRAIN_MONTHS)
        if nxt is not None:
            assert nxt[1] == t1                                   # no gap, no overlap between test quarters
    assert any(t0 == DESIGN_END for _, t0, _ in f)                # a quarter boundary sits exactly on the window edge


class _TwoCell(_Base):
    name = "two_cell"
    params = {"n": 24}
    grid = {"n": [24, 72]}

    def fill(self, it, df, p, data, sym):
        it["side"] = _breakout(df, p["n"]).astype(np.int8)
        it["stop"] = df["close"] - 3 * ta.atr(df, 24)
        it["trail"] = df["close"] - 3 * ta.atr(df, 24)


@pytest.fixture(scope="module")
def long_market():
    """Two synthetic symbols over the real protocol calendar (2022-04 .. validation end)."""
    n = int((VALIDATION_END - pd.Timestamp("2022-04-01", tz=UTC)) / pd.Timedelta(hours=1))
    d = synth(n_sym=2, n=n, seed=11, start="2022-04-01")
    d = {BTC: d[BTC], "PF_ETHUSD": d["PF_S1USD"]}
    return Market(data=d, base=make_base(d, slip_bps=3.0, end=VALIDATION_END))


def test_parameter_choice_for_a_quarter_cannot_see_that_quarter(long_market):
    s = _TwoCell()
    cells = harness.grid_cells(s)
    its = [s.intents(long_market.data, c) for c in cells]
    feeds = [attach(long_market.base, it) for it in its]
    wf = harness.walk_forward(s, feeds, cells, VALIDATION_END, Costs(), Risk())
    k = 6                                                         # the quarter starting 2025-04-01
    t0 = pd.Timestamp(wf["chosen"][k]["test_start"], tz=UTC)
    # wipe every intent from that quarter onward, in every cell: choices up to and including k must not move
    its2 = []
    for it in its:
        d = {}
        for sym, f in it.items():
            g = f.copy()
            g.loc[g.index >= t0, "side"] = 0
            d[sym] = g
        its2.append(d)
    wf2 = harness.walk_forward(s, [attach(long_market.base, it) for it in its2], cells, VALIDATION_END, Costs(), Risk())
    assert [c["cell"] for c in wf["chosen"][:k + 1]] == [c["cell"] for c in wf2["chosen"][:k + 1]]
    assert [c["train_objective"] for c in wf["chosen"][:k + 1]] == [c["train_objective"] for c in wf2["chosen"][:k + 1]]
    for a, b in zip(wf["parts"][:k], wf2["parts"][:k]):
        assert a["trades"] == b["trades"]
    assert len({c["cell"] for c in wf["chosen"]}) >= 1 and sum(len(p["trades"]) for p in wf["parts"]) > 100


def test_regime_score_must_use_validation_quarters_only(long_market):
    # DEFECT: LA-5  (bear/chop score is computed on the stitched curve from 2023-10, i.e. incl. 15 DESIGN months)
    res = harness.audit(_TwoCell(), long_market)
    days_scored = sum(v["days"] for v in res["regimes_trend"].values())
    validation_days = (VALIDATION_END - DESIGN_END).days
    assert days_scored <= validation_days, (days_scored, validation_days)
