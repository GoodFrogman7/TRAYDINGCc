"""config/bot.yaml: defaults, validation, strategy loading, fingerprints."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from desk.bot import config as C
from desk.engine.core import Risk
from desk.strategies.ref_donchian import STRATEGY as DONCHIAN
from test_bot_fakes import no_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")
ROOT = Path(__file__).resolve().parents[1]
DON = "{strategy: desk.strategies.ref_donchian, params: {n: 48}}"


def load(tmp_path, text: str) -> C.BotConfig:
    p = tmp_path / "bot.yaml"
    p.write_text(text)
    return C.load_config(p)


def bad(tmp_path, text: str, match: str) -> None:
    with pytest.raises(C.ConfigError, match=match):
        load(tmp_path, text)


def test_minimal_config_gets_every_default(tmp_path):
    cfg = load(tmp_path, "mode: paper\n")
    assert cfg.kill is False
    assert cfg.books == {"champion": None, "challenger_1": None, "challenger_2": None}
    assert tuple(cfg.books) == C.BOOK_NAMES
    want = dataclasses.replace(Risk(), guardian=True, compounding=False)
    assert cfg.risk == want                       # the backtests' limits, unchanged
    assert (cfg.window_bars, cfg.settle_seconds, cfg.extra_symbols) == (3000, 120, ())
    assert (cfg.stale_feed_minutes, cfg.max_clock_skew_seconds) == (90, 30)
    assert (cfg.delist_after_bars, cfg.max_catchup_bars) == (72, 2000)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.kill = True


def test_shipped_config_is_paper_with_no_champion_and_the_watch_list():
    # 2026-11-18: no strategy earned champion; two refuted finalists trade as paper-only shadow books.
    cfg = C.load_config(ROOT / "config" / "bot.yaml")
    assert cfg.kill is False
    assert cfg.books["champion"] is None
    assert tuple(b.module for k, b in cfg.books.items() if k != "champion" and b is not None) == ("desk.strategies.s_cross_weekend_follow_alts", "desk.strategies.s_trend_quiet_grind")
    assert cfg.risk == Risk()
    assert cfg.window_bars == 5200          # trend_quiet_grind gives no signal on less than about 4660 bars


def test_books_and_strategy_loading(tmp_path):
    cfg = load(tmp_path, f"mode: paper\nchampion: {DON}\n"
                         "challengers:\n  - {strategy: desk.strategies.ref_donchian}\n")
    champ = cfg.books["champion"]
    assert champ == C.BookConfig("champion", "desk.strategies.ref_donchian", {"n": 48})
    assert cfg.books["challenger_1"].params == {} and cfg.books["challenger_2"] is None
    strat, params = C.load_strategy(champ)
    assert strat is DONCHIAN
    assert params == {**DONCHIAN.params, "n": 48}
    fp = C.fingerprint(champ, strat, params, 10000)
    assert fp == {"module": "desk.strategies.ref_donchian", "name": "ref_donchian", "params": params,
                  "valid_bars": DONCHIAN.valid_bars, "max_hold": DONCHIAN.max_hold, "equity0": 10000.0}
    other = C.fingerprint(champ, strat, {**params, "n": 49}, 10000)
    assert other != fp and C.fingerprint(champ, strat, params, 5000) != fp


def test_only_paper_mode_is_accepted(tmp_path):
    bad(tmp_path, "mode: live\n", "paper")
    bad(tmp_path, "kill: false\n", "mode")
    bad(tmp_path, "mode: Paper\n", "paper")
    bad(tmp_path, "", "mode")
    bad(tmp_path, "- paper\n", "mapping")
    with pytest.raises(C.ConfigError, match="not found|cannot read"):
        C.load_config(tmp_path / "missing.yaml")
    (tmp_path / "broken.yaml").write_text("mode: [paper\n")
    with pytest.raises(C.ConfigError, match="YAML"):
        C.load_config(tmp_path / "broken.yaml")


def test_unknown_keys_are_refused_at_every_level(tmp_path):
    bad(tmp_path, "mode: paper\nleverage: 5\n", "unknown")
    bad(tmp_path, "mode: paper\naccount: {equity0: 10000, margin: 2}\n", "unknown")
    bad(tmp_path, "mode: paper\nguardian: {daily_loss: 0.01}\n", "unknown")
    bad(tmp_path, "mode: paper\nfeed: {window: 10}\n", "unknown")
    bad(tmp_path, "mode: paper\nchampion: {strategy: desk.strategies.ref_donchian, size: 2}\n", "unknown")


def test_credential_like_keys_are_refused_anywhere(tmp_path):
    for key in ("api_key", "API_SECRET", "auth_token", "password", "feed_KeY"):
        bad(tmp_path, f"mode: paper\n{key}: abc\n", "credential")
    bad(tmp_path, "mode: paper\nfeed: {access_token: abc}\n", "credential")
    bad(tmp_path, "mode: paper\nchampion: {strategy: desk.strategies.ref_donchian, params: {secret_n: 1}}\n",
        "credential")


def test_challengers_at_most_two(tmp_path):
    one = "{strategy: desk.strategies.ref_donchian}"
    cfg = load(tmp_path, f"mode: paper\nchallengers: [{one}, {one}]\n")
    assert cfg.books["challenger_2"] is not None
    bad(tmp_path, f"mode: paper\nchallengers: [{one}, {one}, {one}]\n", "two")
    bad(tmp_path, f"mode: paper\nchallengers: {one}\n", "list")


def test_strategy_must_be_a_desk_strategy_module_with_known_params(tmp_path):
    bad(tmp_path, "mode: paper\nchampion: {strategy: os.path}\n", "desk.strategies")
    bad(tmp_path, "mode: paper\nchampion: {strategy: desk.strategies.no_such_thing}\n", "import")
    bad(tmp_path, "mode: paper\nchampion: {strategy: desk.strategies.ta}\n", "STRATEGY")
    bad(tmp_path, "mode: paper\nchampion: {strategy: desk.strategies.ref_donchian.x}\n", "desk.strategies")
    bad(tmp_path, "mode: paper\nchampion: {params: {n: 3}}\n", "strategy")
    bad(tmp_path, "mode: paper\nchampion: desk.strategies.ref_donchian\n", "mapping")
    bad(tmp_path, "mode: paper\nchampion: {strategy: desk.strategies.ref_donchian, params: {lookback: 3}}\n",
        "lookback")


@pytest.mark.parametrize("text", [
    "account: {risk_per_trade: 0.006}",
    "guardian: {daily_loss_limit: 0.05}",
    "guardian: {max_consec_losses: 4}",
    "guardian: {max_pos_mult: 1.5}",
    "guardian: {max_gross_mult: 3.5}",
    "guardian: {max_positions: 11}",
    "guardian: {min_stop_pct: 0.001}",
    "guardian: {max_stop_pct: 0.3}",
])
def test_limits_may_only_be_tightened(tmp_path, text):
    bad(tmp_path, f"mode: paper\n{text}\n", "tighten")


def test_tighter_limits_are_accepted_and_reach_the_engine_risk(tmp_path):
    cfg = load(tmp_path, "mode: paper\nkill: true\naccount: {equity0: 5000, risk_per_trade: 0.0025}\n"
                         "guardian: {daily_loss_limit: 0.02, max_consec_losses: 2, halt_sticky: true,\n"
                         "           max_pos_mult: 0.5, max_gross_mult: 2, max_positions: 4,\n"
                         "           min_stop_pct: 0.004, max_stop_pct: 0.1}\n"
                         "feed: {window_bars: 500, extra_symbols: [PF_SOLUSD], stale_feed_minutes: 60}\n")
    r = cfg.risk
    assert cfg.kill is True
    assert (r.equity0, r.risk_per_trade, r.daily_loss_limit, r.max_consec_losses) == (5000.0, 0.0025, 0.02, 2)
    assert (r.halt_sticky, r.max_pos_mult, r.max_gross_mult, r.max_positions) == (True, 0.5, 2.0, 4)
    assert (r.min_stop_pct, r.max_stop_pct, r.guardian, r.compounding) == (0.004, 0.1, True, False)
    assert (cfg.window_bars, cfg.extra_symbols, cfg.stale_feed_minutes) == (500, ("PF_SOLUSD",), 60)


@pytest.mark.parametrize("text", [
    "kill: maybe",
    "account: {equity0: -1}",
    "account: {equity0: lots}",
    "account: {risk_per_trade: 0}",
    "guardian: {max_positions: 0}",
    "guardian: {max_consec_losses: 1.5}",
    "guardian: {halt_sticky: 1}",
    "guardian: {min_stop_pct: 0.3}",
    "guardian: {daily_loss_limit: true}",
    "feed: {window_bars: 0}",
    "feed: {settle_seconds: -5}",
    "feed: {extra_symbols: PF_SOLUSD}",
    "feed: {max_catchup_bars: many}",
    "account: [1, 2]",
])
def test_wrong_types_and_ranges_are_refused(tmp_path, text):
    with pytest.raises(C.ConfigError):
        load(tmp_path, f"mode: paper\n{text}\n")
