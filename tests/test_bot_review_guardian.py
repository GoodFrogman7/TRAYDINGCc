"""Adversarial review of the paper bot, lens: the Guardian and safety.

Tests marked  # DEFECT: <id>  FAIL on the code under review; each shows one finding.
The other tests pass: they pin behaviour the review verified.
No network (fake source, sockets blocked) and nothing is written outside tmp_path.
"""
from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd
import pytest

from desk.bot import config as C
from desk.bot import feed as F
from desk.bot import guardian as G
from desk.bot import paper
from desk.strategies.ref_donchian import STRATEGY as DONCHIAN
from test_bot_fakes import (ALTS, BTC, ETH, HOUR, PARAMS, SYMBOLS, FakeSource, fake_strategy_module,  # noqa: F401
                            make_frames, no_network, read_jsonl, world)

pytestmark = pytest.mark.usefixtures("no_network")
K0 = 2000
MODEL = {"pooled_a": 0.0, "pooled_k": 1.0 / 24.0, "per_symbol": {}}


def has_position(st) -> bool:
    return bool(st["positions"])


def tick_until(world, k: int, cond, limit: int = 500) -> int:
    for kk in range(k, k + limit):
        hb = world.tick(world.bar(kk))
        assert hb["books"]["champion"]["status"] == "ok", hb
        if cond(world.book()["engine"]):
            return kk
    raise AssertionError("the fake market never produced the situation this test needs")


def status_after(world, k: int) -> dict:
    return paper.status(world.state, now=world.bar(k) + HOUR + pd.Timedelta(minutes=10))


# =========================================================================== defects
# DEFECT: G1  a feed that has NEVER been usable is reported healthy for ever
@pytest.mark.parametrize("fault", ["required symbol never fetched", "venue clock never readable"])
def test_a_feed_that_was_never_usable_is_not_reported_healthy_for_ever(world, fault):
    """First deployment, and the live path fails from the first tick (it was never run against the real
    venue). `feed_frozen` needs the previous heartbeat's feed_time, which does not exist yet, so the only
    alert is a `warn`: 12 hours later the heartbeat still says ok, `status` says HEALTHY, the CLI exits 0
    (green GitHub job), and the bot has not processed a single bar."""
    hb = None
    for k in range(K0, K0 + 12):
        now = world.bar(k) + HOUR + pd.Timedelta(minutes=7)
        if fault == "required symbol never fetched":
            world.source.fail = {ETH}
            world.source.now = now
        else:
            world.source.now = None                                  # server_time() answers None
        hb = paper.tick(world.config, world.state, now=now, source=world.source)
    assert not hb["feed"]["usable"] and hb["books"]["champion"]["status"] == "waiting"   # nothing ever ran
    assert not (world.state / "champion.json").exists()
    st = status_after(world, K0 + 11)
    assert not hb["ok"] or not st["healthy"], \
        f"12 hours without one usable tick and the bot reports healthy: {st['why']!r}, alerts {hb['alerts']}"


# DEFECT: G1b  the frozen-feed kill has no clock of its own: it depends on heartbeat.json
def test_the_frozen_feed_kill_does_not_depend_on_the_heartbeat_file(world):
    """Positions are open, the heartbeat file is lost (deleted by hand, a bad merge on bot-state) and a
    required symbol cannot be fetched. The book's own last bar is hours old, but nothing halts."""
    k = tick_until(world, K0, has_position)
    (world.state / "heartbeat.json").unlink()
    world.source.fail = {ALTS[1]}
    for kk in range(k + 1, k + 7):                                   # six hours without a usable feed
        hb = world.tick(world.bar(kk))
    st = world.book()["engine"]
    assert st["last_time"] == world.bar(k).isoformat() and st["positions"]       # (verified: no bar invented)
    assert hb["feed"]["frozen"] and st["halted"], \
        f"6 h without data, open positions, feed frozen={hb['feed']['frozen']}, halted={st['halted']}, ok={hb['ok']}"


# DEFECT: G2  the Guardian's own halts (-3% day, losing streak) raise no alert
def test_a_guardian_halt_on_losses_raises_an_alert(world):
    """`kill everything at -3% on the day or three losses in a row` is the Guardian's main job. When it
    fires, alerts.jsonl stays silent, the heartbeat says ok and the tick exits 0: the report's alert section
    reads `none` on the day the Guardian closed the book."""
    world.write_config(guardian={"max_consec_losses": 1})            # tightened, so it fires quickly
    k = tick_until(world, K0, lambda st: st["halted"])
    st = world.book()["engine"]
    assert "losing trades in a row" in st["halt_reason"]             # (verified: the engine halt is persisted)
    hb = json.loads((world.state / "heartbeat.json").read_text())
    assert hb["books"]["champion"]["halted"]                         # (verified: visible in the heartbeat)
    halted_tick = [a for a in world.alerts() if a["tick_utc"] == hb["tick_utc"]]
    assert any(a["book"] == "champion" and "halt" in (a["code"] + " " + a["message"]).lower() for a in halted_tick), \
        f"book halted ({st['halt_reason']}) at bar {world.bar(k)} with no alert; alerts this tick: {halted_tick}"


class Flaky(type(DONCHIAN)):
    name = "review_flaky_donchian"
    armed = False

    def intents(self, data, p):
        if self.armed:
            raise RuntimeError("strategy bug")
        return super().intents(data, p)


# DEFECT: G3  the kill switch does not reach a book whose strategy raises
def test_the_kill_switch_reaches_a_book_whose_strategy_raises(world, monkeypatch):
    """The halt is applied in memory, then strategy.intents raises and nothing is committed. The moment a
    strategy starts failing is exactly when the owner reaches for the kill switch: the book keeps its
    positions and orders, is not halted, and the heartbeat shows killed: true next to halted: false."""
    flaky = Flaky()
    mod = fake_strategy_module(monkeypatch, "zz_review_flaky", flaky)
    world.write_config(champion={"strategy": mod, "params": PARAMS})
    k = tick_until(world, K0, has_position)
    flaky.armed = True
    (world.state / "KILL").write_text("")
    hb = world.tick(world.bar(k + 1))
    hb = world.tick(world.bar(k + 2))
    st = world.book()["engine"]
    assert hb["killed"]
    assert st["halted"] and st["halt_reason"] == "manual kill", \
        f"kill switch ON for two ticks, book halted={st['halted']}, positions={sorted(st['positions'])}"
    assert not st["positions"] and not st["orders"]


# DEFECT: G4  a held symbol's bar that arrives one tick late is processed as "no bar" and never redone
def test_a_late_bar_of_a_held_symbol_is_replayed_not_skipped(world):
    """Only BTC decides whether the feed is late. If another symbol's newest candle is not served yet, the
    bot invents a flat bar for it and moves on; when the real bar appears an hour later it is never
    processed. Here that bar trades through the position's stop: on time the stop fills, late it does not."""
    k = tick_until(world, K0, lambda st: any(s != BTC for s in st["positions"]))
    sym, pos = next((s, p) for s, p in world.book()["engine"]["positions"].items() if s != BTC)
    bar = world.bar(k + 1)
    df = world.frames[sym]
    if pos["side"] > 0:
        df.loc[bar, "low"] = min(df.loc[bar, "low"], pos["stop"] * 0.995)
    else:
        df.loc[bar, "high"] = max(df.loc[bar, "high"], pos["stop"] * 1.005)
    ontime = world.root / "state_ontime"
    shutil.copytree(world.state, ontime)

    def stop_exits(state_dir):
        return [t for t in read_jsonl(state_dir / "ledger_champion.jsonl")
                if t["symbol"] == sym and t["exit_time"] == bar.isoformat() and t["reason"] == "stop"]

    for kk in (k + 1, k + 2):                                        # control: every bar served on time
        now = world.bar(kk) + HOUR + pd.Timedelta(minutes=7)
        world.source.now = now
        paper.tick(world.config, ontime, now=now, source=world.source)
    assert len(stop_exits(ontime)) == 1                              # (verified: the stop fills on time)

    world.source.last_bar[sym] = world.bar(k)                        # the venue has not served sym's bar yet
    hb = world.tick(bar)
    assert hb["ok"] and hb["feed"]["usable"]
    world.source.last_bar.clear()                                    # one hour later the bar is there
    world.tick(world.bar(k + 2))
    assert len(stop_exits(world.state)) == 1, \
        f"{sym}: bar {bar} traded through the stop {pos['stop']:.6g} but was processed as a missing bar; " \
        f"position still open: {sym in world.book()['engine']['positions']}"


def small(n: int = 120) -> pd.DataFrame:
    return make_frames(n=n)[ALTS[0]]


# DEFECT: G5  an infinite price counts as a real bar
def test_prepare_treats_an_infinite_price_as_a_bad_bar():
    raw = small()
    i = raw.index
    raw.loc[i[50], "high"] = np.inf
    raw.loc[i[60], "close"] = np.inf
    data, _, bad = F.prepare({ALTS[0]: raw.copy()}, i[-1], 72, MODEL)
    df = data[ALTS[0]]
    assert np.isfinite(df[["open", "high", "low", "close"]].to_numpy()).all(), "an infinite price reached the engine"
    assert bad == {ALTS[0]: 2}


# DEFECT: G6  a 90% one-bar print passes straight through to the engine
def test_prepare_flags_a_bar_printed_90_percent_away_from_mark_and_spot():
    """One whole bar prints at a tenth of the price while the venue's own mark and index prices (columns
    mark_close and spot_close of the same row) do not move. Nothing questions it: the engine fills a stop
    at that open and marks the book to that close."""
    raw = small()
    i = raw.index
    raw.loc[i[80], ["open", "high", "low", "close"]] = raw.loc[i[80], ["open", "high", "low", "close"]] * 0.1
    data, _, bad = F.prepare({ALTS[0]: raw.copy()}, i[-1], 72, MODEL)
    row = data[ALTS[0]].loc[i[80]]
    assert bad.get(ALTS[0]) == 1 and row["bar_missing"], \
        f"close {row['close']:.4g} against mark {row['mark_close']:.4g}: accepted as a real bar"


# DEFECT: G7  when the alert log cannot be written the heartbeat on disk stays at the last good tick
def test_a_tick_that_cannot_write_its_alerts_still_updates_the_heartbeat(world, monkeypatch):
    world.tick(world.bar(K0))
    assert status_after(world, K0)["healthy"]

    def full_disk(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(G, "write_alerts", full_disk)
    world.source.skew = pd.Timedelta(minutes=5)                      # a critical alert this tick
    hb = world.tick(world.bar(K0 + 1))
    assert not hb["ok"]                                              # (verified: the returned heartbeat fails)
    on_disk = json.loads((world.state / "heartbeat.json").read_text())
    assert on_disk["tick_utc"] == hb["tick_utc"] and not on_disk["ok"], \
        f"heartbeat.json still shows tick {on_disk['tick_utc']} ok={on_disk['ok']}; status: " \
        f"{status_after(world, K0 + 1)['why']!r}"


# DEFECT: G8  with a broken config the KILL file is not even looked at
def test_the_kill_file_is_reported_even_when_the_config_is_broken(world):
    """A config is most likely to be broken while someone edits it to stop the bot."""
    k = tick_until(world, K0, has_position)
    world.config.write_text("mode: paper\nkill: true\n  champion: [oops\n")
    (world.state / "KILL").write_text("")
    hb = world.tick(world.bar(k + 1))
    assert not hb["ok"] and world.alerts("config_invalid")           # (verified: reported as critical)
    assert world.book()["engine"]["last_time"] == world.bar(k).isoformat()      # (verified: no bar processed)
    assert hb["killed"], "state/KILL exists but the heartbeat says killed: false"


# ============================================================ verified behaviour (pass)
def test_a_losing_streak_halt_flattens_blocks_entries_and_survives_reloads(world):
    world.write_config(guardian={"max_consec_losses": 1})
    k = tick_until(world, K0, lambda st: st["halted"])
    halt_day = world.bar(k).floor("D")
    created = lambda: [d["time"] for d in read_jsonl(world.state / "decisions_champion.jsonl")  # noqa: E731
                       if d["event"] == "order_created"]
    n_created = len(created())
    hb = world.tick(world.bar(k + 1))
    st = world.book()["engine"]
    assert st["halted"] and not st["positions"] and not st["orders"]             # flat one bar after the halt
    kk = k + 2
    while world.bar(kk) < halt_day + pd.Timedelta(days=1):                      # the state is reloaded every tick
        hb = world.tick(world.bar(kk))
        assert hb["books"]["champion"]["halted"] and hb["books"]["champion"]["halt_reason"]
        kk += 1
    assert len(created()) == n_created                                          # no entry while halted
    hb = world.tick(world.bar(kk))                                              # next UTC day: lifts by itself
    assert not hb["books"]["champion"]["halted"]


def test_halt_sticky_keeps_a_loss_halt_across_midnight(world):
    world.write_config(guardian={"max_consec_losses": 1, "halt_sticky": True})
    k = tick_until(world, K0, lambda st: st["halted"])
    for kk in range(k + 1, k + 30):
        hb = world.tick(world.bar(kk))
    assert world.bar(k + 29).floor("D") > world.bar(k).floor("D")
    assert hb["books"]["champion"]["halted"] and not world.book()["engine"]["positions"]


def test_kill_is_committed_while_the_feed_is_not_usable(world):
    k = tick_until(world, K0, has_position)
    world.source.fail = {ALTS[0]}
    (world.state / "KILL").write_text("")
    hb = world.tick(world.bar(k + 1))
    st = world.book()["engine"]
    assert hb["killed"] and not hb["feed"]["usable"]
    assert st["halted"] and st["halt_reason"] == "manual kill" and not st["orders"]
    assert all(p["exit_pending"] == "guardian" for p in st["positions"].values())
    assert st["last_time"] == world.bar(k).isoformat()                          # no bar invented


def test_a_stale_btc_alone_stops_every_book(world):
    k = tick_until(world, K0, has_position)
    world.source.last_bar[BTC] = world.bar(k)                                   # only BTC stops printing
    hb = world.tick(world.bar(k + 1))
    assert hb["books"]["champion"]["status"] == "idle" and world.alerts("feed_late")
    hb = world.tick(world.bar(k + 2))
    assert hb["feed"]["frozen"] and not hb["ok"] and world.book()["engine"]["halted"]
    assert world.book()["engine"]["last_time"] == world.bar(k).isoformat()


def test_zero_negative_nan_and_crossed_bars_never_reach_the_engine(world):
    for s, col, v in ((ALTS[0], "close", 0.0), (ALTS[1], "low", -1.0), (ALTS[2], "open", np.nan)):
        world.frames[s].loc[world.bar(K0 + 1), col] = v
    world.tick(world.bar(K0))
    hb = world.tick(world.bar(K0 + 1))
    assert hb["ok"] and {a["symbol"] for a in world.alerts("bad_bar")} == set(ALTS)
    frames = {s: df[df.index <= world.bar(K0 + 1)].iloc[-50:] for s, df in world.frames.items()}
    data, _, bad = F.prepare(frames, world.bar(K0 + 1), 72, MODEL)
    base = F.build_base(data, world.bar(K0 + 1))
    for s in ALTS:
        a = base.arrays[s]
        assert bad[s] == 1 and not a["tradable"][-1]
        assert a["o"][-1] == a["h"][-1] == a["l"][-1] == a["c"][-1] == a["c"][-2] > 0


@pytest.mark.parametrize("text", ["mode: live\n", "mode: Paper\n", "mode: [paper]\n", "mode: paper\nmode: live\n",
                                  "mode: 'paper '\n", "kill: false\n", "mode: paper\nlive: true\n",
                                  "mode: paper\naccount: {api_key: x}\n", "mode: paper\nfeed: {auth_token: x}\n"])
def test_anything_but_plain_paper_mode_is_refused(tmp_path, text):
    path = tmp_path / "bot.yaml"
    path.write_text(text)
    with pytest.raises(C.ConfigError):
        C.load_config(path)
    hb = paper.tick(path, tmp_path / "state", now=pd.Timestamp("2026-09-22 09:07", tz="UTC"),
                    source=FakeSource(make_frames(n=10)))
    assert not hb["ok"] and hb["mode"] == "paper" and hb["books"] == {} and hb["feed"]["symbols"] == 0
    assert not list((tmp_path / "state").glob("*.jsonl")) or [p.name for p in (tmp_path / "state").glob("*.jsonl")] \
        == ["alerts.jsonl"]


def test_limits_cannot_be_loosened_or_switched_off(tmp_path):
    path = tmp_path / "bot.yaml"
    for section, key, value in (("guardian", "daily_loss_limit", 0.05), ("guardian", "max_consec_losses", 4),
                                ("guardian", "daily_loss_limit", 0), ("guardian", "max_consec_losses", 0),
                                ("guardian", "max_gross_mult", 5.0), ("guardian", "guardian", False),
                                ("account", "risk_per_trade", 0.02), ("guardian", "daily_loss_limit", float("nan"))):
        path.write_text(json.dumps({"mode": "paper", section: {key: value}}).replace("NaN", ".nan"))
        with pytest.raises(C.ConfigError):
            C.load_config(path)
