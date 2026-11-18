"""What the ship stage added after the two reviews (tests/test_bot_review_*.py hold the reviewers' own cases):
a symbol the venue stops answering for, catch-up ticks with a kill release, halts that must reach a failing
book, damaged state values, the off-market print filter, challenger slots, and the owner-facing status lines.
No network (fake source, sockets blocked) and nothing is written outside tmp_path."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

from desk.bot import config as C
from desk.bot import feed as F
from desk.bot import guardian as G
from desk.bot import paper
from desk.bot import report as R
from desk.engine.core import Costs, Engine, Order, Position, Risk, State, attach
from desk.strategies.ref_donchian import STRATEGY as DONCHIAN
from test_bot_fakes import (ALTS, BTC, ETH, HOUR, PARAMS, SYMBOLS, FakeSource, World,  # noqa: F401
                            fake_strategy_module, make_frames, no_network, read_jsonl, world)

pytestmark = pytest.mark.usefixtures("no_network")
K0 = 2000
DON = "desk.strategies.ref_donchian"
MODEL = {"pooled_a": 0.0, "pooled_k": 1.0 / 24.0, "per_symbol": {}}


def has_position(st) -> bool:
    return bool(st["positions"])


def tick_until(w, k: int, cond, limit: int = 400) -> int:
    for kk in range(k, k + limit):
        w.tick(w.bar(kk))
        if cond(w.book()["engine"]):
            return kk
    raise AssertionError("the fake market never produced the situation this test needs")


def twin_of(w) -> World:
    root = w.root / "twin"
    root.mkdir()
    return World(root)


def without_tick(path) -> list[dict]:
    rows = read_jsonl(path)
    for r in rows:
        r.pop("tick_utc", None)
    return rows


class Crash(BaseException):
    """The process dying: not an Exception, so nothing in the bot may catch it."""


# ------------------------------------------------- a symbol the venue stops answering for
def test_a_universe_symbol_nobody_holds_stops_blocking_the_bot_and_is_taken_back_when_it_answers(world):
    world.write_config(champion=None, feed={"delist_after_bars": 3})
    world.tick(world.bar(K0))
    sym = ALTS[0]
    world.source.fail = {sym}
    hbs = [world.tick(world.bar(K0 + i)) for i in (1, 2, 3)]
    assert [hb["feed"]["usable"] for hb in hbs] == [False, False, False]
    first = hbs[0]["tick_utc"]
    assert all(hb["feed"]["failing_since"] == {sym: first} for hb in hbs)      # the run of failures has one start
    assert [hb["feed"]["frozen"] for hb in hbs] == [False, True, True]
    hb = world.tick(world.bar(K0 + 4))                         # three hours of failures: given up, the rest goes on
    assert hb["feed"]["usable"] and not hb["feed"]["frozen"] and hb["ok"]
    assert hb["feed"]["failed"] == [sym] and hb["feed"]["failing_since"] == {sym: first}
    gone = world.alerts("symbol_delisted")
    assert len(gone) == 1 and gone[0]["symbol"] == sym and gone[0]["level"] == "warn"
    assert gone[0]["detail"]["hours_failing"] == pytest.approx(3.0) and "fake outage" in gone[0]["detail"]["error"]
    assert len(world.alerts("feed_incomplete")) == 3           # ... and it no longer counts as an incomplete feed
    world.source.fail = set()
    hb = world.tick(world.bar(K0 + 5))                         # the venue answers again: an ordinary symbol again
    assert hb["feed"]["usable"] and hb["feed"]["failing_since"] == {} and hb["feed"]["failed"] == []
    assert len(world.alerts("symbol_delisted")) == 1


def test_an_outage_of_everything_is_not_held_against_one_symbol(world):
    world.write_config(champion=None, feed={"delist_after_bars": 3})
    world.tick(world.bar(K0))
    world.source.fail = set(SYMBOLS)                           # the venue is down: BTC fails too
    for i in (1, 2, 3, 4, 5):
        hb = world.tick(world.bar(K0 + i))
        assert not hb["feed"]["usable"] and hb["feed"]["failing_since"] == {}
    world.source.fail = {ALTS[1]}                              # back, except one symbol: ITS clock starts now
    hb = world.tick(world.bar(K0 + 6))
    assert not hb["feed"]["usable"] and hb["feed"]["failing_since"] == {ALTS[1]: hb["tick_utc"]}
    assert not world.alerts("symbol_delisted")
    first = hb["tick_utc"]
    world.source.fail = {BTC, ALTS[1]}                         # BTC is never given up, however long it fails,
    for i in range(7, 12):                                     # and nothing is concluded about others meanwhile
        hb = world.tick(world.bar(K0 + i))
        assert not hb["feed"]["usable"] and hb["feed"]["failing_since"] == {ALTS[1]: first}
    assert hb["feed"]["frozen"] and not world.alerts("symbol_delisted")
    world.source.fail = {ALTS[1]}                              # BTC is back and this one has failed for six hours
    hb = world.tick(world.bar(K0 + 12))
    assert hb["feed"]["usable"] and [a["symbol"] for a in world.alerts("symbol_delisted")] == [ALTS[1]]


def test_a_dead_symbol_with_only_an_order_has_the_order_cancelled(world):
    world.write_config(feed={"delist_after_bars": 2})
    k = tick_until(world, K0, lambda st: any(s in ALTS for s in st["orders"]) and not st["positions"])
    sym = next(s for s in world.book()["engine"]["orders"] if s in ALTS)
    world.source.fail = {sym}
    for i in (1, 2, 3):
        hb = world.tick(world.bar(k + i))
    assert hb["feed"]["usable"] and sym not in world.book()["engine"]["orders"]
    gone = [d for d in read_jsonl(world.state / "decisions_champion.jsonl")
            if d["symbol"] == sym and d["event"] == "order_cancelled"]
    assert gone and world.book()["engine"]["last_time"] == world.bar(k + 3).isoformat()


def test_build_base_ghost_is_a_symbol_without_bars_and_the_engine_closes_it_as_delisted(world):
    frames = {s: df.iloc[:300] for s, df in make_frames().items() if s in (BTC, ETH)}
    t_last = frames[BTC].index[-1]
    data, _, _ = F.prepare(frames, t_last, 72, MODEL)
    base = F.build_base(data, t_last, {"PF_GONEUSD": 12.5, "PF_ODDUSD": float("nan"), BTC: 1.0})
    assert set(base.arrays) == {BTC, ETH, "PF_GONEUSD", "PF_ODDUSD"} and len(base.index) == 300
    for s in ("PF_GONEUSD", "PF_ODDUSD"):
        a = base.arrays[s]
        assert a["valid"].tolist() == [True] + [False] * 299 and not a["tradable"].any()
    assert base.arrays["PF_GONEUSD"]["c"][0] == 12.5 and base.arrays["PF_ODDUSD"]["c"][0] == 1.0
    assert np.array_equal(base.arrays[BTC]["c"], F.build_base(data, t_last).arrays[BTC]["c"])   # a real frame wins
    last = base.index[-2].isoformat()
    st = State(cash=10_000.0, equity=10_000.0, day_start_equity=10_000.0, last_time=last)
    st.positions["PF_GONEUSD"] = Position("PF_GONEUSD", 1, 10.0, 12.0, last, 11.0, 11.0, float("nan"), 10.0,
                                          False, False, last_price=12.5)
    st.orders["PF_ODDUSD"] = Order("PF_ODDUSD", 1, float("nan"), 0.9, float("nan"), 1, last)
    eng = Engine(Costs(), Risk(), state=st, log_events=True)
    eng.run(attach(base, {}), len(base.index) - 1, len(base.index))
    assert not st.positions and not st.orders
    assert [(t["symbol"], t["reason"]) for t in eng.trades] == [("PF_GONEUSD", "delisted")]
    assert eng.trades[0]["exit_price"] == pytest.approx(12.5, rel=0.02) and eng.trades[0]["exit_price"] < 12.5
    assert ("PF_ODDUSD", "order_cancelled", "no bar") in [(e["symbol"], e["event"], e.get("reason")) for e in eng.events]


# ------------------------------------------------------------ catch-up ticks (S2, continued)
def test_releasing_the_kill_switch_after_missed_hours_gives_the_same_result_as_hourly_ticks(world):
    hourly, late = world, twin_of(world)
    k = tick_until(hourly, K0, has_position)
    for kk in range(K0, k + 1):
        late.tick(late.bar(kk))
    for w in (hourly, late):
        (w.state / "KILL").write_text("")
        w.tick(w.bar(k + 1))
    assert late.book()["engine"] == hourly.book()["engine"] and hourly.book()["engine"]["halted"]
    gap = 30                                                   # crosses a UTC midnight: the kill halt must not lapse
    for kk in range(k + 2, k + gap):
        hourly.tick(hourly.bar(kk))
    assert hourly.bar(k + gap).floor("D") > hourly.bar(k + 1).floor("D")
    for w in (hourly, late):
        (w.state / "KILL").unlink()
        w.tick(w.bar(k + gap))
        w.tick(w.bar(k + gap + 1))
    assert late.book()["engine"] == hourly.book()["engine"] and not late.book()["engine"]["halted"]
    for name in ("ledger_champion.jsonl", "decisions_champion.jsonl"):
        assert without_tick(late.state / name) == without_tick(hourly.state / name), name
    created = [d["time"] for d in read_jsonl(late.state / "decisions_champion.jsonl") if d["event"] == "order_created"]
    assert not [x for x in created if late.bar(k).isoformat() < x < late.bar(k + gap).isoformat()]   # no entry while killed
    resumed = late.alerts("resumed")
    assert len(resumed) == 1 and resumed[0]["level"] == "info" and resumed[0]["book"] == "champion"


def test_a_frozen_feed_seen_by_a_catch_up_tick_halts_before_the_newest_bar_only(world):
    k = tick_until(world, K0, has_position)
    held = sorted(world.book()["engine"]["positions"])
    for s in SYMBOLS:
        world.source.last_bar[s] = world.bar(k + 8)            # the venue stopped printing at bar k+8 ...
    hb = world.tick(world.bar(k + 12))                         # ... and the bot wakes up four hours later
    assert hb["feed"]["usable"] and hb["feed"]["frozen"] and hb["books"]["champion"]["halted"]
    st = world.book()["engine"]
    assert st["last_time"] == world.bar(k + 8).isoformat() and st["halt_reason"] == "frozen data feed"
    forced = [t for t in read_jsonl(world.state / "ledger_champion.jsonl") if t["reason"] == "guardian"]
    assert forced and {t["exit_time"] for t in forced} == {world.bar(k + 8).isoformat()}   # not eleven hours earlier
    halts = [d for d in read_jsonl(world.state / "decisions_champion.jsonl") if d["event"] == "guardian_halt"
             and d["reason"] == "frozen data feed"]
    assert [d["time"] for d in halts] == [world.bar(k + 7).isoformat()] and held


def test_a_swap_after_missed_hours_still_closes_when_the_old_strategy_cannot_be_run(world, monkeypatch):
    class Dying(type(DONCHIAN)):
        name = "ship_dying"
        armed = False

        def intents(self, data, p):
            if self.armed:
                raise RuntimeError("gone")
            return super().intents(data, p)

    dying = Dying()
    mod = fake_strategy_module(monkeypatch, "zz_ship_dying", dying)
    world.write_config(champion={"strategy": mod, "params": PARAMS})
    k = tick_until(world, K0, has_position)
    dying.armed = True
    world.write_config(champion={"strategy": DON, "params": PARAMS})
    hb = world.tick(world.bar(k + 5))
    assert hb["ok"] and hb["books"]["champion"]["status"] == "ok" and world.book()["strategy"]["module"] == DON
    assert world.book()["started_bar"] == world.bar(k + 5).isoformat()
    old = next((world.state / "archive").glob("champion.*.swapped"))
    assert json.loads((old / "champion.json").read_text())["engine"]["last_time"] == world.bar(k + 5).isoformat()
    assert not json.loads((old / "champion.json").read_text())["engine"]["positions"]
    assert len(pd.read_csv(old / "equity_champion.csv")) == k + 5 - K0 + 1          # no bar skipped
    warn = [a for a in world.alerts("missed_bars") if "could not be run" in a["message"]]
    assert len(warn) == 1 and warn[0]["level"] == "warn" and "4 missed bar(s)" in warn[0]["message"]


# ------------------------------------------------- a halt must reach a book that cannot run
class Flaky(type(DONCHIAN)):
    name = "ship_flaky"
    armed = False

    def intents(self, data, p):
        if self.armed:
            raise RuntimeError("strategy bug")
        return super().intents(data, p)


def flaky_world(world, monkeypatch) -> Flaky:
    flaky = Flaky()
    world.write_config(champion={"strategy": fake_strategy_module(monkeypatch, "zz_ship_flaky", flaky), "params": PARAMS})
    return flaky


def test_a_frozen_feed_flattens_a_book_whose_strategy_raises(world, monkeypatch):
    flaky = flaky_world(world, monkeypatch)
    k = tick_until(world, K0, has_position)
    flaky.armed = True
    for s in SYMBOLS:
        world.source.last_bar[s] = world.bar(k)
    world.tick(world.bar(k + 1))
    hb = world.tick(world.bar(k + 2))                          # frozen: the halt is put on record, no bar to run
    assert hb["feed"]["frozen"] and world.book()["engine"]["halt_reason"] == "frozen data feed"
    world.source.last_bar.clear()
    for s in SYMBOLS:
        world.source.last_bar[s] = world.bar(k + 1)            # one bar arrives, the feed is still frozen
    hb = world.tick(world.bar(k + 3))
    st = world.book()["engine"]
    assert hb["feed"]["frozen"] and not st["positions"] and st["last_time"] == world.bar(k + 1).isoformat()
    assert hb["books"]["champion"]["status"] == "error" and "without the strategy" in hb["books"]["champion"]["detail"]
    err = world.alerts("book_error")
    assert len(err) == 1 and "being flattened (frozen data feed)" in err[0]["message"]


def test_without_a_kill_or_freeze_a_failing_strategy_still_leaves_the_book_untouched(world, monkeypatch):
    flaky = flaky_world(world, monkeypatch)
    k = tick_until(world, K0, has_position)
    before = world.book()
    flaky.armed = True
    hb = world.tick(world.bar(k + 1))
    assert not hb["ok"] and hb["books"]["champion"]["status"] == "error" and world.book() == before


def test_the_kill_switch_is_put_on_record_even_when_the_bars_cannot_be_run_at_all(world, monkeypatch):
    k = tick_until(world, K0, has_position)
    rows = len(pd.read_csv(world.state / "equity_champion.csv"))

    real = paper.attach

    def broken(*a, **kw):
        raise RuntimeError("cannot build the bars")
    monkeypatch.setattr(paper, "attach", broken)
    (world.state / "KILL.txt").write_text("stop")              # as a text editor saves it
    hb = world.tick(world.bar(k + 1))
    st = world.book()["engine"]
    assert hb["killed"] and not hb["ok"] and hb["books"]["champion"]["status"] == "error"
    assert st["halted"] and st["halt_reason"] == "manual kill" and not st["orders"]
    assert st["positions"] and all(p["exit_pending"] == "guardian" for p in st["positions"].values())
    assert st["last_time"] == world.bar(k).isoformat()         # no bar was invented
    assert len(pd.read_csv(world.state / "equity_champion.csv")) == rows
    assert hb["books"]["champion"]["halted"] and len(world.alerts("book_error")) == 1
    monkeypatch.setattr(paper, "attach", real)
    hb = world.tick(world.bar(k + 2))                          # bars run again: the stored halt sells at the first one
    assert hb["killed"] and hb["books"]["champion"]["status"] == "ok"
    exits = [t for t in read_jsonl(world.state / "ledger_champion.jsonl") if t["reason"] == "guardian"]
    assert not world.book()["engine"]["positions"] and {t["exit_time"] for t in exits} == {world.bar(k + 1).isoformat()}


def test_a_book_whose_numbers_are_not_finite_is_never_written(world, monkeypatch):
    k = tick_until(world, K0, has_position)
    before = (world.state / "champion.json").read_bytes()
    real = paper._run_bars

    def poisoned(t, eng, bars, i0, i1):
        real(t, eng, bars, i0, i1)
        eng.state.equity = float("inf")
    monkeypatch.setattr(paper, "_run_bars", poisoned)
    hb = world.tick(world.bar(k + 1))
    assert not hb["ok"] and hb["books"]["champion"]["status"] == "error"
    assert (world.state / "champion.json").read_bytes() == before
    assert "not a number" in world.alerts("book_error")[0]["message"]
    monkeypatch.setattr(paper, "_run_bars", real)
    hb = world.tick(world.bar(k + 2))
    assert hb["books"]["champion"]["status"] == "ok" and hb["books"]["champion"]["lag_bars"] == 0
    assert not world.alerts("state_unreadable")


# ----------------------------------------------------------------- loss halts are announced
def test_a_loss_halt_is_critical_for_the_champion_and_a_warning_for_a_shadow_book(world):
    world.write_config(challengers=[{"strategy": DON, "params": PARAMS}], guardian={"max_consec_losses": 1})
    k = tick_until(world, K0, lambda st: st["halted"])
    hb = json.loads((world.state / "heartbeat.json").read_text())
    alerts = [a for a in world.alerts("guardian_halt")]
    assert {(a["book"], a["level"]) for a in alerts} == {("champion", "critical"), ("challenger_1", "warn")}
    assert all(a["detail"]["bar"] == world.bar(k).isoformat() and "losing trades in a row" in a["detail"]["reason"]
               and "until the next UTC day" in a["message"] for a in alerts)
    assert not hb["ok"] and hb["error"] is None and hb["alerts"]["critical"] == 1
    st = paper.status(world.state, now=world.bar(k) + HOUR + pd.Timedelta(minutes=10))
    assert not st["healthy"] and st["why"] == "the last tick raised critical alert(s): guardian_halt"
    assert st["trading"].startswith("champion ref_donchian is HALTED by the Guardian: 1 losing trades in a row")
    hb = world.tick(world.bar(k + 1))                          # announced once, not every hour
    assert hb["ok"] and len(world.alerts("guardian_halt")) == 2


# ------------------------------------------------------------------- state values (N4)
@pytest.mark.parametrize("damage", ["last_time", "log_bytes", "position_null", "position_text", "order_null",
                                    "started_bar", "halted"])
def test_parseable_but_damaged_state_values_retire_the_book_instead_of_failing_every_tick(world, damage):
    k = tick_until(world, K0, lambda st: st["positions"] and st["orders"])
    doc = world.book()
    pos = next(iter(doc["engine"]["positions"].values()))
    order = next(iter(doc["engine"]["orders"].values()))
    if damage == "last_time":
        doc["engine"]["last_time"] = "yesterday-ish"
    elif damage == "log_bytes":
        doc["log_bytes"]["equity"] = -1
    elif damage == "position_null":
        pos["stop"] = None
    elif damage == "position_text":
        pos["qty"] = "a lot"
    elif damage == "order_null":
        order["stop"] = None
    elif damage == "started_bar":
        doc["started_bar"] = None
    else:
        doc["engine"]["halted"] = "no"
    (world.state / "champion.json").write_text(json.dumps(doc))
    hb = world.tick(world.bar(k + 1))
    assert [a["code"] for a in world.alerts() if a["level"] == "critical"] == ["state_unreadable"]
    assert hb["error"] is None and hb["books"]["champion"]["status"] == "ok"
    assert world.book()["started_bar"] == world.bar(k + 1).isoformat()
    assert len(list((world.state / "archive").glob("champion.*.unreadable"))) == 1


def test_a_sound_state_with_open_orders_and_positions_is_not_called_damaged(world):
    k = tick_until(world, K0, lambda st: st["positions"] and st["orders"])
    doc = world.book()
    assert any(o["limit"] is None for o in doc["engine"]["orders"].values())       # NaN is stored as null
    st, fp, started, sizes = paper._parse_state(world.state / "champion.json", "champion")
    assert sorted(st.positions) == sorted(doc["engine"]["positions"]) and started == world.bar(K0).isoformat()
    hb = world.tick(world.bar(k + 1))
    assert hb["ok"] or not world.alerts("state_unreadable")


def test_a_state_file_that_cannot_be_read_right_now_fails_the_tick_but_is_not_retired(world, monkeypatch):
    k = tick_until(world, K0, has_position)
    before = (world.state / "champion.json").read_bytes()
    real = paper.Path.read_bytes

    def flaky_disk(self):
        if self.name == "champion.json":
            raise PermissionError(13, "Permission denied")
        return real(self)
    monkeypatch.setattr(paper.Path, "read_bytes", flaky_disk)
    hb = world.tick(world.bar(k + 1))
    monkeypatch.setattr(paper.Path, "read_bytes", real)
    assert not hb["ok"] and "PermissionError" in hb["error"] and [a["code"] for a in world.alerts()] == ["tick_error"]
    assert (world.state / "champion.json").read_bytes() == before and not (world.state / "archive").exists()
    hb = world.tick(world.bar(k + 2))
    assert hb["books"]["champion"]["lag_bars"] == 0 and world.alerts("missed_bars")


def test_the_alert_for_a_retired_book_is_on_record_before_its_files_move(world, monkeypatch):
    world.tick(world.bar(K0))
    (world.state / "champion.json").write_text("{broken")
    real = os.replace

    def dying(src, dst):
        if "archive" in str(dst):
            raise Crash()
        return real(src, dst)
    monkeypatch.setattr(paper.os, "replace", dying)
    with pytest.raises(Crash):
        world.tick(world.bar(K0 + 1))
    monkeypatch.setattr(paper.os, "replace", real)
    on_record = world.alerts("state_unreadable")
    assert len(on_record) == 1 and on_record[0]["level"] == "critical" and "archive" in on_record[0]["detail"]["archived_to"]
    assert (world.state / "champion.json").exists()            # the crash came first; the next tick retires it
    hb = world.tick(world.bar(K0 + 2))
    assert hb["books"]["champion"]["status"] == "ok" and not hb["ok"] and len(world.alerts("state_unreadable")) == 2


# -------------------------------------------------------------------- wrong clock (S5)
def test_with_an_unreadable_venue_clock_nothing_is_fetched_or_retired(world):
    world.write_config(feed={"max_catchup_bars": 10})
    world.tick(world.bar(K0))
    world.source.calls.clear()
    now = world.bar(K0 + 40) + HOUR + pd.Timedelta(minutes=7)
    world.source.now = None                                    # server_time() answers None
    hb = paper.tick(world.config, world.state, now=now, source=world.source)
    assert not hb["feed"]["usable"] and not hb["feed"]["frozen"] and hb["ok"] and world.source.calls == []
    assert (world.state / "champion.json").exists() and not world.alerts("state_too_old")
    assert hb["feed"]["unusable_since"] == hb["tick_utc"] and hb["feed"]["feed_time"] == world.bar(K0).isoformat()
    hb = world.tick(world.bar(K0 + 40))                        # the clock can be checked again: only now is it too old
    assert world.alerts("state_too_old") and hb["feed"]["unusable_since"] is None


def test_a_wrong_clock_does_not_start_or_stop_the_unusable_run(world):
    world.tick(world.bar(K0))
    world.source.fail = {ETH}
    hb1 = world.tick(world.bar(K0 + 1))
    world.source.skew = pd.Timedelta(minutes=10)
    hb2 = world.tick(world.bar(K0 + 2))
    assert hb2["feed"]["unusable_since"] == hb1["feed"]["unusable_since"] == hb1["tick_utc"]
    assert not hb2["feed"]["frozen"] and hb2["feed"]["failing_since"] == hb1["feed"]["failing_since"]
    assert not world.book()["engine"]["halted"]


def test_fetch_uses_a_clock_that_was_read_earlier(world):
    src = FakeSource(make_frames(n=400))
    asked = []
    src.server_time = lambda: asked.append(1) or pd.Timestamp("2026-07-10 00:07", tz="UTC")
    when, delay = F.venue_clock(src)
    assert when == pd.Timestamp("2026-07-10 00:07", tz="UTC") and 0.0 <= delay < 1.0 and asked == [1]
    got = F.fetch(src, [BTC], pd.Timestamp("2026-07-03", tz="UTC"), pd.Timestamp("2026-07-10", tz="UTC"),
                  clock=(when, 0.25))
    assert asked == [1] and got.server_time == when and got.server_time_delay == 0.25 and BTC in got.frames

    def down():
        raise RuntimeError("clock endpoint down")
    src.server_time = down
    assert F.venue_clock(src)[0] is None


# -------------------------------------------------------------- off-market prints (G6)
def small(n: int = 120) -> pd.DataFrame:
    return make_frames(n=n)[ALTS[0]]


def prepared(raw: pd.DataFrame):
    data, _, bad = F.prepare({ALTS[0]: raw.copy()}, raw.index[-1], 72, MODEL)
    return data[ALTS[0]], bad.get(ALTS[0], 0)


def test_a_real_crash_that_mark_and_index_prices_follow_is_not_a_bad_bar():
    raw = small()
    i = raw.index
    cols = ["open", "high", "low", "close", "mark_close", "spot_close"]
    raw.loc[i[80]:, cols] = raw.loc[i[80]:, cols] * 0.45       # the whole market reprices by 55% and stays there
    raw.loc[i[80], ["open", "high"]] = raw.loc[i[79], "close"]  # the crash bar opens at the old price
    df, bad = prepared(raw)
    assert bad == 0 and not df["bar_missing"].any() and df.loc[i[80], "close"] == raw.loc[i[80], "close"]


def test_a_bad_open_alone_is_a_bad_bar_but_a_wick_is_not():
    raw = small()
    i = raw.index
    raw.loc[i[70], "low"] = raw.loc[i[70], "low"] * 0.2        # a wick: the engine never fills at a low
    raw.loc[i[80], ["open", "low"]] = raw.loc[i[80], "close"] * 0.1     # the first print of the hour is nonsense
    raw.loc[i[90], ["close", "high"]] = raw.loc[i[90], "open"] * 4.0    # ... and so is the last print of this one
    df, bad = prepared(raw)
    assert bad == 2 and not df.loc[i[70], "bar_missing"]
    for k in (80, 90):
        row = df.loc[i[k]]
        assert row["bar_missing"] and row["open"] == row["high"] == row["low"] == row["close"] == raw["close"].iloc[k - 1]
    assert not df.loc[i[91], "bar_missing"]                    # the bar after a bad print is judged on its own prices


def test_one_surviving_reference_is_enough_and_no_reference_means_no_verdict():
    raw = small()
    i = raw.index
    raw.loc[i[60], "mark_close"] = raw.loc[i[60], "mark_close"] * 10    # the mark price is the one that is wrong
    raw.loc[i[80], ["open", "high", "low", "close"]] = raw.loc[i[80], ["open", "high", "low", "close"]] * 0.1
    raw.loc[i[80], "spot_close"] = np.nan                      # index price missing: the mark price still convicts
    _, bad = prepared(raw)
    assert bad == 1
    bare = raw[["open", "high", "low", "close", "volume"]]     # no mark or index prices at all: left alone
    df, bad = prepared(bare)
    assert bad == 0 and not df["bar_missing"].any()
    raw.loc[i[80], "mark_close"] = np.nan                      # neither reference on that bar; the bar before has
    raw.loc[i[81], ["mark_close", "spot_close"]] = np.nan      # them, so the open is judged, the close cannot be
    df, bad = prepared(raw)
    assert bad == 1 and df.loc[i[80], "bar_missing"]


def test_a_bar_whose_high_or_low_contradicts_its_open_and_close_is_a_bad_bar():
    raw = small()
    i = raw.index
    raw.loc[i[50], "high"] = min(raw.loc[i[50], "open"], raw.loc[i[50], "close"]) * 0.999
    raw.loc[i[60], "low"] = max(raw.loc[i[60], "open"], raw.loc[i[60], "close"]) * 1.001
    df, bad = prepared(raw)
    assert bad == 2 and df.loc[i[50], "bar_missing"] and df.loc[i[60], "bar_missing"]


def test_a_bad_print_does_not_fill_the_stop_of_a_held_position(world):
    k = tick_until(world, K0, lambda st: any(p["side"] > 0 and s != BTC for s, p in st["positions"].items()))
    sym, pos = next((s, p) for s, p in world.book()["engine"]["positions"].items() if p["side"] > 0 and s != BTC)
    bar = world.bar(k + 1)
    cols = ["open", "high", "low", "close"]
    world.frames[sym].loc[bar, cols] = world.frames[sym].loc[bar, cols] * 0.1
    hb = world.tick(bar)                                       # the newest bar is there, just nonsense: no waiting
    assert hb["ok"] and hb["books"]["champion"]["lag_bars"] == 0
    now = world.book()["engine"]["positions"][sym]
    assert now["last_price"] == pos["last_price"] and now["stop"] == pos["stop"]
    assert not [t for t in read_jsonl(world.state / "ledger_champion.jsonl") if t["exit_time"] == bar.isoformat()
                and t["symbol"] == sym]
    flagged = [a for a in world.alerts("bad_bar") if a["symbol"] == sym]
    assert len(flagged) == 1 and "off-market" in flagged[0]["message"]


# ------------------------------------------------------------------ challenger slots (S4)
A = {"strategy": DON, "params": {**PARAMS, "n": 36}}
B = {"strategy": DON, "params": {**PARAMS, "n": 48}}
CC = {"strategy": DON, "params": {**PARAMS, "n": 60}}


def slots(w) -> dict:
    return {n: (w.book(n)["strategy"]["params"]["n"], w.book(n)["started_bar"])
            for n in ("challenger_1", "challenger_2") if (w.state / f"{n}.json").exists()}


def test_reordering_the_challengers_restarts_nothing(world):
    world.write_config(challengers=[A, B])
    for kk in range(K0, K0 + 10):
        world.tick(world.bar(kk))
    start = world.bar(K0).isoformat()
    assert slots(world) == {"challenger_1": (36, start), "challenger_2": (48, start)}
    world.write_config(challengers=[B, A])
    hb = world.tick(world.bar(K0 + 10))
    assert slots(world) == {"challenger_1": (36, start), "challenger_2": (48, start)}
    assert hb["ok"] and world.alerts() == [] and not (world.state / "archive").exists()
    assert all(world.book(n)["engine"]["last_time"] == world.bar(K0 + 10).isoformat() for n in slots(world))


def test_removing_one_challenger_and_adding_another_keeps_the_survivor(world):
    world.write_config(challengers=[A, B])
    for kk in range(K0, K0 + 10):
        world.tick(world.bar(kk))
    start = world.bar(K0).isoformat()
    world.write_config(challengers=[B])                       # A is dropped: B stays where its book is
    hb = world.tick(world.bar(K0 + 10))
    assert slots(world) == {"challenger_2": (48, start)} and hb["books"]["challenger_1"]["status"] == "empty"
    assert [a["book"] for a in world.alerts("strategy_changed")] == ["challenger_1"]
    world.write_config(challengers=[B, CC])                   # a new one takes the free slot
    world.tick(world.bar(K0 + 11))
    assert slots(world) == {"challenger_1": (60, world.bar(K0 + 11).isoformat()), "challenger_2": (48, start)}
    world.write_config(challengers=[CC])                      # B is dropped: C stays in slot 1
    world.tick(world.bar(K0 + 12))
    assert slots(world) == {"challenger_1": (60, world.bar(K0 + 11).isoformat())}
    world.write_config(challengers=[A, CC])                   # nothing matches slot 2 any more: plain positions
    world.tick(world.bar(K0 + 13))
    assert slots(world) == {"challenger_1": (60, world.bar(K0 + 11).isoformat()),
                            "challenger_2": (36, world.bar(K0 + 13).isoformat())}


# ------------------------------------------------------------------- owner-facing lines
def test_status_says_what_is_trading_not_only_that_the_bot_is_alive(world, capsys):
    world.write_config(champion=None, challengers=[A])
    world.tick(world.bar(K0))
    now = world.bar(K0) + HOUR + pd.Timedelta(minutes=10)
    st = paper.status(world.state, now=now)
    assert st["healthy"] and st["trading"].startswith("nothing: no champion strategy is configured")
    assert "1 challenger book(s) running" in st["trading"]
    text = R.render(R.build_report(world.state, now=now))
    assert "**HEALTHY**: ok" in text and "**Trading**: nothing: no champion strategy is configured" in text
    world.write_config()
    world.tick(world.bar(K0 + 1))
    st = paper.status(world.state, now=now + HOUR)
    assert st["trading"] == "champion ref_donchian, 0 position(s), 0 order(s)"
    (world.state / "KILL").write_text("")
    world.tick(world.bar(K0 + 2))
    assert paper.status(world.state, now=now + 2 * HOUR)["trading"] == "nothing: the kill switch is ON"
    assert paper.status(world.root / "nowhere")["trading"] == "nothing"
    paper.main(["status", "--state", str(world.state)])
    assert "Trading: nothing: the kill switch is ON" in capsys.readouterr().out


def test_status_is_not_healthy_while_the_bot_has_never_had_usable_data(world):
    world.source.fail = {ETH}
    hb = world.tick(world.bar(K0))                             # the very first tick: only a warning so far
    assert hb["ok"] and not hb["feed"]["usable"] and hb["feed"]["feed_time"] is None
    st = paper.status(world.state, now=world.bar(K0) + HOUR + pd.Timedelta(minutes=10))
    assert not st["healthy"] and "never had usable market data" in st["why"]
    assert "not trading yet: waiting" in st["trading"]
    hb = world.tick(world.bar(K0 + 1))                         # an hour later it is a frozen feed: critical
    assert not hb["ok"] and hb["feed"]["frozen"] and world.alerts("feed_frozen")[0]["level"] == "critical"
    world.source.fail = set()
    hb = world.tick(world.bar(K0 + 2))
    assert hb["ok"] and paper.status(world.state, now=world.bar(K0 + 2) + HOUR + pd.Timedelta(minutes=10))["healthy"]


def test_a_broken_config_with_the_kill_file_says_what_happens_to_the_kill(world):
    world.tick(world.bar(K0))
    world.config.write_text("mode: paper\n  oops: [\n")
    hb = world.tick(world.bar(K0 + 1))
    assert not hb["killed"] and "KILL" not in world.alerts("config_invalid")[0]["message"]
    (world.state / "kill").write_text("")
    hb = world.tick(world.bar(K0 + 2))
    msg = world.alerts("config_invalid")[1]["message"]
    assert hb["killed"] and "KILL file was seen" in msg and "after the config is fixed" in msg
    world.write_config()
    hb = world.tick(world.bar(K0 + 3))
    assert hb["killed"] and world.book()["engine"]["halt_reason"] == "manual kill"


# ------------------------------------------------------------------------------ config
@pytest.mark.parametrize("key, loose, tight", [("stale_feed_minutes", 91, 60), ("max_clock_skew_seconds", 31, 10)])
def test_the_frozen_feed_and_clock_limits_may_only_be_tightened(tmp_path, key, loose, tight):
    path = tmp_path / "bot.yaml"
    path.write_text(f"mode: paper\nfeed: {{{key}: {loose}}}\n")
    with pytest.raises(C.ConfigError, match="looser"):
        C.load_config(path)
    path.write_text(f"mode: paper\nfeed: {{{key}: {tight}}}\n")
    assert getattr(C.load_config(path), key) == tight
    path.write_text("mode: paper\n")
    assert (C.load_config(path).stale_feed_minutes, C.load_config(path).max_clock_skew_seconds) == (90, 30)


def test_kill_requested_reads_the_same_file_the_tick_does(tmp_path):
    path = tmp_path / "bot.yaml"
    path.write_text("mode: paper\n")
    cfg = C.load_config(path)
    assert not G.kill_requested(cfg, tmp_path / "state")       # no state directory yet: no switch
    (tmp_path / "KILL.txt").write_text("")
    assert G.kill_requested(cfg, tmp_path)


# ---------------------------------------------------------------------- lock, alert log
def test_a_stale_lock_is_broken_by_one_starter_only(world, monkeypatch):
    import time as _time
    world.tick(world.bar(K0))
    lock = world.state / "tick.lock"
    lock.write_text("{}")
    old = _time.time() - 30 * 60
    os.utime(lock, (old, old))
    real = os.rename

    def overtaken(src, dst):                                   # another starter breaks the lock and takes it
        if os.path.basename(str(src)) == "tick.lock":          # in the instant before our rename
            os.utime(src, None)
        return real(src, dst)
    monkeypatch.setattr(paper.os, "rename", overtaken)
    hb = world.tick(world.bar(K0 + 1))
    assert hb.get("skipped") and lock.exists()                 # the live lock was given back, nothing ran
    assert [p.name for p in world.state.glob("*.lock")] == ["tick.lock"]
    assert world.book()["engine"]["last_time"] == world.bar(K0).isoformat()
    monkeypatch.setattr(paper.os, "rename", real)
    os.utime(lock, (old, old))
    hb = world.tick(world.bar(K0 + 1))                         # really stale: broken, with a warning
    assert not hb.get("skipped") and [a["code"] for a in world.alerts()] == ["lock_stale"]
    assert not list(world.state.glob("*.lock"))


def test_an_alert_appended_after_a_torn_line_is_still_readable(tmp_path):
    (tmp_path / "alerts.jsonl").write_bytes(b'{"tick_utc": "2026-07-10T14:07:00+00:00", "code": "old"}\n{"tick_utc": "2026')
    G.write_alerts(tmp_path, [G.Alert("critical", "feed_frozen", "x")], "2026-07-10T15:07:00+00:00")
    assert [r["code"] for r in paper.read_log(tmp_path, "alerts")] == ["old", "feed_frozen"]
    G.write_alerts(tmp_path, [G.Alert("warn", "feed_late", "y")], "2026-07-10T16:07:00+00:00")
    assert (tmp_path / "alerts.jsonl").read_text().count("\n\n") == 0
    assert [r["code"] for r in paper.read_log(tmp_path, "alerts")] == ["old", "feed_frozen", "feed_late"]


# ----------------------------------------------------------------------------- runbook
def test_every_alert_the_bot_can_raise_is_explained_in_the_runbook():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = "".join(p.read_text() for p in sorted((root / "desk" / "bot").glob("*.py")))
    level = r'"(?:info|warn|critical)"'
    raised = set(re.findall(rf'(?:alert|Alert)\(\s*{level}(?: if [^,]+ else {level})?,\s*"([a-z_]+)"', source))
    explained = set(re.findall(r"^\| `([a-z_]+)`", (root / "docs" / "RUNBOOK.md").read_text(), flags=re.M))
    assert len(raised) >= 22 and raised == explained
