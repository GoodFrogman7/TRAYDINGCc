"""Strategies in the bot see `feed.window_bars` of history and the bot's symbol set, not four years
and every symbol. For every configured strategy the newest intents must be the same either way;
if they are not, raise `feed.window_bars` (or do not configure that strategy).

The data-dependent cases need the research dataset (`python -m desk.data.download`) and are skipped
without it. They are evaluated at the END OF THE VALIDATION WINDOW under `store.ceiling`, so the
sealed holdout is never read by this test.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from desk.bot import config as C
from desk.bot import feed as F
from desk.data import store
from desk.engine.costs import slip_series
from desk.strategies.base import Strategy, blank_intents
from desk.strategies.ref_donchian import STRATEGY as DONCHIAN
from test_bot_fakes import HOUR, PARAMS, SYMBOLS, no_network, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")
ROOT = Path(__file__).resolve().parents[1]
LAST = 200                         # newest intents compared
PRICE_TOL = 1e-9                   # relative
HAVE_DATA = store.H1.exists() and any(store.H1.glob("*.parquet"))
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="research data absent: run python -m desk.data.download")


def compare_intents(window: dict[str, pd.DataFrame], full: dict[str, pd.DataFrame], last: int = LAST) -> list[str]:
    """Differences between the newest `last` intents computed on the bot's window and on full history."""
    problems = []
    for s, w in window.items():
        x = w.iloc[-last:]
        if s not in full:
            problems.append(f"{s}: no intents on full history")
            continue
        y = full[s].reindex(x.index)
        for col in ("side", "exit"):
            a = np.nan_to_num(x[col].to_numpy(dtype="float64"))
            b = np.nan_to_num(y[col].to_numpy(dtype="float64"))
            if not np.array_equal(a, b):
                at = x.index[np.nonzero(a != b)[0][0]]
                problems.append(f"{s}: `{col}` differs on {int((a != b).sum())} bar(s), first at {at}")
        for col in ("limit", "stop", "tp", "trail"):
            a, b = x[col].to_numpy(dtype="float64"), y[col].to_numpy(dtype="float64")
            if not np.array_equal(np.isnan(a), np.isnan(b)):
                problems.append(f"{s}: `{col}` is set on different bars")
                continue
            ok = ~np.isnan(a)
            if ok.any():
                worst = float(np.max(np.abs(a[ok] - b[ok]) / np.abs(b[ok])))
                if worst > PRICE_TOL:
                    problems.append(f"{s}: `{col}` differs by {worst:.2e} relative")
    return problems


def bot_window(frames: dict[str, pd.DataFrame], universe: dict, asof: pd.Timestamp, window_bars: int,
               extra: tuple = ()) -> dict[str, pd.DataFrame]:
    """What the bot's strategies are given on the tick that closes bar asof - 1h: the symbol set of
    `symbols_needed`, `window_bars` + 1 bars, passed through `prepare`."""
    start = asof - (window_bars + 1) * HOUR
    required, context = F.symbols_needed(universe, start, asof, set(), tuple(extra))
    raw = {}
    for s in required + context:
        if s in frames:
            df = frames[s]
            df = df[(df.index >= start) & (df.index < asof)].drop(columns=["funding", "funding_is_est"], errors="ignore")
            if len(df):
                raw[s] = df
    data, _, _ = F.prepare(raw, asof - HOUR, 72)
    return data


# ---------------------------------------------------- always run (synthetic market)
def test_window_check_passes_for_a_short_memory_strategy(world):
    frames = world.frames
    asof = frames[SYMBOLS[0]].index[-1] + HOUR
    p = {**DONCHIAN.params, **PARAMS}
    data = bot_window(frames, store.universe(), asof, 600)
    full, _, _ = F.prepare({s: df.copy() for s, df in frames.items()}, asof - HOUR, 72)
    assert all(len(df) == 601 for df in data.values()) and set(data) == set(SYMBOLS)
    assert compare_intents(DONCHIAN.intents(data, p), DONCHIAN.intents(full, p)) == []
    # the same strategy on too short a window: its 12-bar average range has not settled 50 bars in
    short = bot_window(frames, store.universe(), asof, 250)
    assert any("`stop` differs" in x for x in compare_intents(DONCHIAN.intents(short, p), DONCHIAN.intents(full, p)))


def test_window_check_catches_a_strategy_that_needs_more_history(world):
    class LongMemory(Strategy):
        name = "long_memory"

        def intents(self, data, p):
            out = {}
            for s, df in data.items():
                it = blank_intents(df.index)
                base = df["close"].expanding().mean()            # depends on where the history starts
                it["side"] = np.where(df["close"] > base, 1, 0).astype(np.int8)
                it["stop"] = base * 0.9
                out[s] = it
            return out

    frames = world.frames
    asof = frames[SYMBOLS[0]].index[-1] + HOUR
    data = bot_window(frames, store.universe(), asof, 300)
    full, _, _ = F.prepare({s: df.copy() for s, df in frames.items()}, asof - HOUR, 72)
    strat = LongMemory()
    problems = compare_intents(strat.intents(data, {}), strat.intents(full, {}))
    assert problems and any("`stop` differs" in p for p in problems)


def test_window_check_catches_a_strategy_that_needs_symbols_outside_the_bot_set(world):
    world.write_universe({"2026-11": list(SYMBOLS[:3])})        # the last two symbols are not fetched by the bot
    frames = world.frames
    asof = frames[SYMBOLS[0]].index[-1] + HOUR
    data = bot_window(frames, store.universe(), asof, 300)
    assert set(data) == set(SYMBOLS[:3])

    class Breadth(Strategy):
        name = "breadth"

        def intents(self, data, p):
            closes = pd.DataFrame({s: df["close"] for s, df in data.items()})
            up = (closes.pct_change(24) > 0).sum(axis=1)         # how many symbols rose: depends on the set
            out = {}
            for s, df in data.items():
                it = blank_intents(df.index)
                it["side"] = np.where(up.reindex(df.index) >= 3, 1, 0).astype(np.int8)
                it["stop"] = df["close"] * 0.95
                out[s] = it
            return out

    full, _, _ = F.prepare({s: df.copy() for s, df in frames.items()}, asof - HOUR, 72)
    strat = Breadth()
    assert any("`side` differs" in p for p in compare_intents(strat.intents(data, {}), strat.intents(full, {})))


# ------------------------------------------------------ need the research dataset
def configured() -> list:
    """(label, module, params) for every strategy in config/bot.yaml, plus the reference strategy so
    the check is never empty."""
    cfg = C.load_config(ROOT / "config" / "bot.yaml")
    out = [pytest.param("desk.strategies.ref_donchian", {}, id="reference:ref_donchian")]
    for name, book in cfg.books.items():
        if book is not None:
            out.append(pytest.param(book.module, book.params, id=f"{name}:{book.module.rsplit('.', 1)[-1]}"))
    return out


@pytest.fixture(scope="module")
def research():
    """Research bars up to the end of VALIDATION (the holdout stays sealed) and the bot's window on them."""
    cfg = C.load_config(ROOT / "config" / "bot.yaml")
    asof = store.VALIDATION_END
    with store.ceiling(asof):
        full = store.load_all()
        window = bot_window(full, store.universe(), asof, cfg.window_bars, cfg.extra_symbols)
        yield {"full": full, "window": window, "asof": asof, "cfg": cfg}


@needs_data
@pytest.mark.parametrize("module,params", configured())
def test_configured_strategy_gives_the_same_intents_on_the_bot_window(research, module, params):
    strategy, p = C.load_strategy(C.BookConfig("champion", module, params))
    on_window = strategy.intents({s: df.copy() for s, df in research["window"].items()}, p)
    on_full = strategy.intents(research["full"], p)
    problems = compare_intents(on_window, on_full)
    assert problems == [], (f"{module} needs more than feed.window_bars = {research['cfg'].window_bars} bars or "
                            f"symbols outside the bot's set: " + "; ".join(problems[:5]))


@needs_data
def test_bot_window_rows_equal_the_research_rows(research):
    """`prepare` on the raw research columns rebuilds the research frame, funding included."""
    assert len(research["window"]) >= 10
    for s, win in research["window"].items():
        ref = research["full"][s].reindex(win.index)
        both = win.index.intersection(research["full"][s].index)[1:]     # row 0 has no earlier premium to estimate from
        assert list(win.columns) == list(ref.columns), s
        w, r = win.loc[both], ref.loc[both]
        pd.testing.assert_frame_equal(w.drop(columns="funding"), r.drop(columns="funding"), check_freq=False,
                                      check_exact=True, obj=s)
        # funding: the venue's rate is copied exactly. Where it is an estimate the research files used the
        # premium before it was stored as float32, so here it can differ in the 7th digit (not so live:
        # the bot gets the premium at full precision, as the downloader did).
        actual = ~r["funding_is_est"].to_numpy()
        assert np.array_equal(w["funding"].to_numpy()[actual], r["funding"].to_numpy()[actual]), s
        assert np.allclose(w["funding"].to_numpy(), r["funding"].to_numpy(), rtol=1e-5, atol=1e-10), s


@needs_data
def test_slippage_table_on_the_window_equals_full_history(research):
    for s, win in research["window"].items():
        full = research["full"][s]
        a = slip_series(win, s).iloc[-2000:]
        b = slip_series(full, s).reindex(a.index)
        both = a.index.intersection(full.index)
        assert np.array_equal(a.loc[both].to_numpy(), b.loc[both].to_numpy()), s
