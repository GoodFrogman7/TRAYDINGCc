"""paper.tick end to end on a fake market: parity with the backtest engine, recovery, halts, swaps."""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
import pytest

from desk.bot import feed as F
from desk.bot import paper
from desk.engine.core import Costs, Engine, Risk, attach
from desk.strategies.base import Strategy, blank_intents
from desk.strategies.ref_donchian import STRATEGY as DONCHIAN
from test_bot_fakes import (ALTS, HOUR, MONTHS, PARAMS, SYMBOLS, fake_strategy_module,  # noqa: F401
                            full_world, no_network, read_jsonl, world)

pytestmark = pytest.mark.usefixtures("no_network")
K0 = 2000                         # first ticked bar: 2026-09-22 08:00, 2000 bars after the fake history starts
DON = "desk.strategies.ref_donchian"


# ---------------------------------------------------------------------- helpers
def run_ticks(world, ks) -> list[dict]:
    return [world.tick(world.bar(k)) for k in ks]


def reference(world, first_k: int, last_k: int, params=PARAMS, risk: Risk | None = None) -> tuple[Engine, pd.Index]:
    """ONE Engine.run over bars first_k..last_k on the whole fake history: what a backtest would give."""
    last = world.bar(last_k)
    frames = {s: df[df.index <= last] for s, df in world.frames.items()}
    data, _, _ = F.prepare(frames, last, 72)
    base = F.build_base(data, last)
    eng = Engine(Costs(), risk or Risk(), DONCHIAN.valid_bars, DONCHIAN.max_hold, log_events=True)
    i0 = int(base.index.get_loc(world.bar(first_k)))
    eng.run(attach(base, DONCHIAN.intents(data, {**DONCHIAN.params, **params})), i0, len(base.index))
    eng.curve = pd.Series(eng.equity_curve[i0:], index=base.index[i0:])
    return eng


def same(a, b) -> bool:
    if isinstance(b, float) and not isinstance(b, bool):
        if a is None:
            return np.isnan(b)
        return a == pytest.approx(b, rel=1e-9, abs=1e-9)
    return a == b


def assert_book_equals(world, book: str, eng: Engine) -> None:
    """Ledger, decisions, equity rows and final state of `book` equal the single engine run."""
    ledger = read_jsonl(world.state / f"ledger_{book}.jsonl")
    assert len(ledger) == len(eng.trades)
    for row, t in zip(ledger, eng.trades):
        assert set(row) == set(t) | {"book", "strategy", "tick_utc"}
        for key, want in t.items():
            assert same(row[key], want), (key, row[key], want)
    decisions = [d for d in read_jsonl(world.state / f"decisions_{book}.jsonl") if d["event"] != "book_started"]
    assert [(d["time"], d["symbol"], d["event"]) for d in decisions] == \
           [(e["time"], e["symbol"], e["event"]) for e in eng.events]
    eq = pd.read_csv(world.state / f"equity_{book}.csv")
    assert list(eq.columns) == ["time", "equity", "gross", "tick_utc"]
    assert eq["time"].tolist() == [t.isoformat() for t in eng.curve.index]
    assert np.allclose(eq["equity"].to_numpy(), eng.curve.to_numpy(), rtol=0, atol=1e-6)
    st = world.book(book)["engine"]
    assert st["equity"] == pytest.approx(eng.state.equity, abs=1e-6)
    assert st["cash"] == pytest.approx(eng.state.cash, abs=1e-6)
    assert st["n_trades"] == eng.state.n_trades and st["last_time"] == eng.state.last_time
    assert sorted(st["positions"]) == sorted(eng.state.positions)
    assert sorted(st["orders"]) == sorted(eng.state.orders)


def tick_until(world, k: int, cond, limit: int = 400) -> int:
    """Tick hourly from bar k until cond(champion state) holds; returns the last ticked bar number."""
    for kk in range(k, k + limit):
        hb = world.tick(world.bar(kk))
        assert hb["books"]["champion"]["status"] == "ok", hb
        if cond(world.book()["engine"]):
            return kk
    raise AssertionError("the fake market never produced the situation this test needs")


def files(world) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(world.state.iterdir()) if p.is_file()}


# ----------------------------------------------- parity with the backtest engine
def test_hourly_ticks_equal_one_engine_run(full_world):
    world = full_world
    last = K0 + 160
    hbs = run_ticks(world, range(K0, last + 1))
    eng = reference(world, K0, last)
    assert len(eng.trades) >= 5                               # the comparison is not vacuous
    assert_book_equals(world, "champion", eng)
    assert all(hb["mode"] == "paper" and hb["error"] is None for hb in hbs)
    # a healthy run raises nothing, except that every loss halt of the Guardian is announced, once, as critical
    halts = [(e["time"], e["reason"]) for e in eng.events if e["event"] == "guardian_halt"]
    alerts = world.alerts()
    assert [(a["code"], a["level"], a["book"]) for a in alerts] == [("guardian_halt", "critical", "champion")] * len(halts)
    assert [(a["detail"]["bar"], a["detail"]["reason"]) for a in alerts] == halts
    assert [hb["tick_utc"] for hb in hbs if not hb["ok"]] == [a["tick_utc"] for a in alerts]
    doc = world.book()
    assert doc["schema"] == 1 and doc["book"] == "champion" and doc["started_bar"] == world.bar(K0).isoformat()
    assert doc["strategy"] == {"module": DON, "name": "ref_donchian", "params": {**DONCHIAN.params, **PARAMS},
                               "valid_bars": 1, "max_hold": 0, "equity0": 10000.0}
    for kind, name in (("decisions", "decisions_champion.jsonl"), ("ledger", "ledger_champion.jsonl"),
                       ("equity", "equity_champion.csv")):
        assert doc["log_bytes"][kind] == (world.state / name).stat().st_size
    first = read_jsonl(world.state / "decisions_champion.jsonl")[0]
    assert first["event"] == "book_started" and first["time"] == world.bar(K0).isoformat()
    assert not (world.state / "tick.lock").exists()


def test_every_decision_line_has_a_reason_and_is_strict_json(world):
    run_ticks(world, range(K0, K0 + 70))
    text = (world.state / "decisions_champion.jsonl").read_text()
    assert "NaN" not in text and "Infinity" not in text
    rows = read_jsonl(world.state / "decisions_champion.jsonl")
    events = {r["event"] for r in rows}
    assert {"book_started", "order_created", "entry", "exit"} <= events
    for r in rows:
        assert list(r)[:6] == ["time", "book", "strategy", "event", "symbol", "reason"]
        assert r["reason"] and r["book"] == "champion" and r["strategy"] == "ref_donchian" and r["tick_utc"]
    market_order = next(r for r in rows if r["event"] == "order_created")
    assert market_order["limit"] is None and market_order["stop"] > 0      # the stop is attached
    assert {r["reason"] for r in rows if r["event"] == "exit"} <= {"stop", "guardian"}


def test_three_books_run_side_by_side(full_world):
    world = full_world
    world.write_config(challengers=[{"strategy": DON, "params": {"n": 48, "atr_n": 12, "stop_atr": 2.0}},
                                    {"strategy": DON, "params": {"n": 12, "atr_n": 12, "stop_atr": 1.5}}])
    last = K0 + 60
    hbs = run_ticks(world, range(K0, last + 1))
    assert_book_equals(world, "champion", reference(world, K0, last))
    assert_book_equals(world, "challenger_1", reference(world, K0, last, {"n": 48, "atr_n": 12, "stop_atr": 2.0}))
    assert_book_equals(world, "challenger_2", reference(world, K0, last, {"n": 12, "atr_n": 12, "stop_atr": 1.5}))
    assert set(hbs[-1]["books"]) == {"champion", "challenger_1", "challenger_2"}
    assert all(b["status"] == "ok" and b["lag_bars"] == 0 for b in hbs[-1]["books"].values())


# -------------------------------------------------------- repeated / missed ticks
def test_repeated_tick_is_a_noop(world):
    run_ticks(world, range(K0, K0 + 30))
    before = files(world)
    hb = world.tick(world.bar(K0 + 29), minutes=20)           # same hour, later minute
    after = files(world)
    assert hb["ok"] and hb["books"]["champion"]["status"] == "idle" and hb["books"]["champion"]["lag_bars"] == 0
    assert set(before) == set(after)
    for name in before:
        if name != "heartbeat.json":
            assert before[name] == after[name], name
    assert json.loads(after["heartbeat.json"])["tick_utc"] != json.loads(before["heartbeat.json"])["tick_utc"]
    # an early tick in the next hour (inside the settle time) is also a no-op
    hb = world.tick(world.bar(K0 + 30), minutes=1)
    assert hb["books"]["champion"]["status"] == "idle"
    assert {n: b for n, b in files(world).items() if n != "heartbeat.json"} == \
           {n: b for n, b in before.items() if n != "heartbeat.json"}


def test_missed_ticks_are_replayed(world):
    run_ticks(world, range(K0, K0 + 40))
    hb = world.tick(world.bar(K0 + 75))                       # the bot was down for 35 hours
    run_ticks(world, range(K0 + 76, K0 + 100))
    assert hb["ok"] and hb["books"]["champion"]["status"] == "ok" and hb["books"]["champion"]["lag_bars"] == 0
    assert_book_equals(world, "champion", reference(world, K0, K0 + 99))
    missed = world.alerts("missed_bars")
    assert len(missed) == 1 and missed[0]["level"] == "warn" and missed[0]["detail"]["bars"] == 36
    assert world.alerts() == missed
    eq = pd.read_csv(world.state / "equity_champion.csv")
    assert eq["time"].is_unique and len(eq) == 100
    assert (eq["tick_utc"] == hb["tick_utc"]).sum() == 36     # replayed rows carry the tick that wrote them


def test_a_state_older_than_max_catchup_is_retired(world):
    world.write_config(feed={"max_catchup_bars": 10})
    run_ticks(world, range(K0, K0 + 5))
    hb = world.tick(world.bar(K0 + 30))
    old = world.alerts("state_too_old")
    assert len(old) == 1 and old[0]["level"] == "critical" and not hb["ok"]
    doc = world.book()
    assert doc["started_bar"] == world.bar(K0 + 30).isoformat() and doc["engine"]["equity"] == 10000.0
    retired = list((world.state / "archive").glob("champion.*.too_old"))
    assert len(retired) == 1 and (retired[0] / "champion.json").exists()
    assert len(pd.read_csv(retired[0] / "equity_champion.csv")) == 5
    assert len(pd.read_csv(world.state / "equity_champion.csv")) == 1


# --------------------------------------------------------------- crash recovery
class Crash(BaseException):
    """Stands in for the process dying: not an Exception, so nothing in the bot may catch it."""


def crash_on_state_write(monkeypatch, book: str = "champion"):
    real = paper.atomic_write_json

    def dying(path, obj):
        if os.path.basename(str(path)) == f"{book}.json":
            raise Crash()
        return real(path, obj)
    monkeypatch.setattr(paper, "atomic_write_json", dying)
    return real


def test_crash_between_log_append_and_state_write_is_rolled_back_and_redone(world, monkeypatch):
    run_ticks(world, range(K0, K0 + 50))
    before = files(world)
    real = crash_on_state_write(monkeypatch)
    with pytest.raises(Crash):
        world.tick(world.bar(K0 + 50))
    crashed = files(world)
    assert crashed["champion.json"] == before["champion.json"]                 # the state was not written ...
    assert len(crashed["equity_champion.csv"]) > len(before["equity_champion.csv"])   # ... but the logs were
    assert not (world.state / "tick.lock").exists()
    monkeypatch.setattr(paper, "atomic_write_json", real)
    world.tick(world.bar(K0 + 51))                            # the next hourly tick redoes bar 50, then 51
    run_ticks(world, range(K0 + 52, K0 + 80))
    assert_book_equals(world, "champion", reference(world, K0, K0 + 79))
    eq = pd.read_csv(world.state / "equity_champion.csv")
    assert eq["time"].is_unique
    lines = (world.state / "decisions_champion.jsonl").read_text().splitlines()
    keys = [(d["time"], d["symbol"], d["event"]) for d in map(json.loads, lines)]
    assert len(keys) == len(set(keys))                        # nothing logged twice
    rolled = world.alerts("log_rollback")
    assert len(rolled) == 1 and rolled[0]["level"] == "warn" and rolled[0]["book"] == "champion"
    assert rolled[0]["detail"]["equity"]["cut_bytes"] > 0


def test_crash_on_the_very_first_tick_leaves_no_orphan_lines(world, monkeypatch):
    real = crash_on_state_write(monkeypatch)
    with pytest.raises(Crash):
        world.tick(world.bar(K0))
    assert not (world.state / "champion.json").exists()
    assert (world.state / "decisions_champion.jsonl").stat().st_size > 0
    monkeypatch.setattr(paper, "atomic_write_json", real)
    run_ticks(world, range(K0 + 1, K0 + 30))
    assert world.book()["started_bar"] == world.bar(K0 + 1).isoformat()
    assert_book_equals(world, "champion", reference(world, K0 + 1, K0 + 29))
    assert [a["code"] for a in world.alerts()] == ["log_rollback"]
    orphan = list((world.state / "archive").glob("champion.*.orphan_logs"))
    assert len(orphan) == 1 and (orphan[0] / "decisions_champion.jsonl").exists()   # kept, not destroyed


def test_a_half_written_log_line_is_cut_off(world):
    run_ticks(world, range(K0, K0 + 10))
    with open(world.state / "ledger_champion.jsonl", "ab") as f:
        f.write(b'{"symbol": "PF_XBTUSD", "pnl": 12')         # torn write, no newline
    with open(world.state / "decisions_champion.jsonl", "ab") as f:
        f.write(b'{"time": "x", "event": "entry"}\n')
    run_ticks(world, range(K0 + 10, K0 + 30))
    assert_book_equals(world, "champion", reference(world, K0, K0 + 29))
    assert len(world.alerts("log_rollback")) == 1


def test_corrupt_state_file_is_retired_and_the_book_restarts_flat(world):
    run_ticks(world, range(K0, K0 + 20))
    (world.state / "champion.json").write_text('{"schema": 1, "book": "champion", "engine": {"cash": 1')
    hb = world.tick(world.bar(K0 + 20))
    assert not hb["ok"] and hb["alerts"]["critical"] == 1
    a = world.alerts("state_unreadable")
    assert len(a) == 1 and a[0]["level"] == "critical" and a[0]["book"] == "champion"
    retired = list((world.state / "archive").glob("champion.*.unreadable"))
    assert len(retired) == 1
    assert {p.name for p in retired[0].iterdir()} >= {"champion.json", "decisions_champion.jsonl",
                                                      "equity_champion.csv"}
    assert len(pd.read_csv(retired[0] / "equity_champion.csv")) == 20        # the old history is kept
    doc = world.book()
    assert doc["started_bar"] == world.bar(K0 + 20).isoformat()
    assert doc["engine"]["equity"] == 10000.0 and not doc["engine"]["positions"]
    assert len(pd.read_csv(world.state / "equity_champion.csv")) == 1
    run_ticks(world, range(K0 + 21, K0 + 50))
    assert_book_equals(world, "champion", reference(world, K0 + 20, K0 + 49))


@pytest.mark.parametrize("damage", ["schema", "engine", "book", "not_json", "list"])
def test_other_unreadable_states_are_retired_too(world, damage):
    run_ticks(world, range(K0, K0 + 3))
    doc = world.book()
    if damage == "schema":
        doc["schema"] = 2
    elif damage == "engine":
        doc["engine"]["surprise"] = 1                         # State.from_json refuses it
    elif damage == "book":
        doc["book"] = "challenger_1"
    text = {"not_json": "\x00\x00\x00", "list": "[1, 2]"}.get(damage, json.dumps(doc))
    (world.state / "champion.json").write_text(text)
    hb = world.tick(world.bar(K0 + 3))
    assert [a["code"] for a in world.alerts()] == ["state_unreadable"] and not hb["ok"]
    assert world.book()["started_bar"] == world.bar(K0 + 3).isoformat()
    assert hb["books"]["champion"]["status"] == "ok"


# -------------------------------------------------------------------------- lock
def test_a_second_tick_sees_the_lock_and_touches_nothing(world, capsys):
    run_ticks(world, range(K0, K0 + 3))
    before = files(world)
    (world.state / "tick.lock").write_text('{"pid": 1}')
    capsys.readouterr()
    hb = world.tick(world.bar(K0 + 3))
    assert "another tick is running" in capsys.readouterr().out
    assert hb["ok"] and hb["skipped"] and hb["alerts"]["critical"] == 0
    after = files(world)
    assert after.pop("tick.lock") == b'{"pid": 1}' and after == before


def test_a_stale_lock_is_broken_with_a_warning(world):
    run_ticks(world, range(K0, K0 + 3))
    lock = world.state / "tick.lock"
    lock.write_text('{"pid": 1}')
    old = time.time() - 21 * 60
    os.utime(lock, (old, old))
    hb = world.tick(world.bar(K0 + 3))
    assert hb["ok"] and hb["books"]["champion"]["status"] == "ok" and not lock.exists()
    a = world.alerts()
    assert [x["code"] for x in a] == ["lock_stale"] and a[0]["level"] == "warn"
    os.utime(world.state, None)
    lock.write_text("")
    young = time.time() - 19 * 60
    os.utime(lock, (young, young))
    assert world.tick(world.bar(K0 + 4)).get("skipped")


# ---------------------------------------------------------------- kill and resume
def has_position(st) -> bool:
    return bool(st["positions"])


def test_kill_flattens_blocks_entries_and_resume_restores(world):
    k = tick_until(world, K0, has_position)
    held = sorted(world.book()["engine"]["positions"])
    (world.state / "KILL").write_text("stop")
    hb = world.tick(world.bar(k + 1))
    assert hb["killed"] and hb["ok"]                          # a kill is a warning, not a failure
    st = world.book()["engine"]
    assert st["halted"] and st["halt_reason"] == "manual kill" and not st["orders"]
    # the kill was seen before bar k+1 was processed, so the positions were sold at that bar's open
    assert not st["positions"]
    exits = [t for t in read_jsonl(world.state / "ledger_champion.jsonl") if t["exit_time"] == world.bar(k + 1).isoformat()]
    assert sorted(t["symbol"] for t in exits) == held and {t["reason"] for t in exits} == {"guardian"}
    halts = [d for d in read_jsonl(world.state / "decisions_champion.jsonl") if d["event"] == "guardian_halt"]
    assert len(halts) == 1 and halts[0]["reason"] == "manual kill" and halts[0]["time"] == world.bar(k).isoformat()
    # ticks continue for two days: still halted across midnight, no entries, equity stays current
    n_orders = sum(d["event"] == "order_created" for d in read_jsonl(world.state / "decisions_champion.jsonl"))
    hbs = run_ticks(world, range(k + 2, k + 50))
    st = world.book()["engine"]
    assert st["halted"] and not st["positions"] and not st["orders"]
    assert st["last_time"] == world.bar(k + 49).isoformat()
    rows = read_jsonl(world.state / "decisions_champion.jsonl")
    assert sum(d["event"] == "order_created" for d in rows) == n_orders
    assert any(d["event"] == "signal_blocked" and "manual kill" in d["reason"] for d in rows)
    assert all(h["killed"] and h["books"]["champion"]["halted"] for h in hbs)
    assert len(world.alerts("killed")) == 49 and world.alerts("killed")[0]["level"] == "warn"
    # removing the file resumes at once
    (world.state / "KILL").unlink()
    hb = world.tick(world.bar(k + 50))
    assert not hb["killed"] and not hb["books"]["champion"]["halted"]
    rows = read_jsonl(world.state / "decisions_champion.jsonl")
    resumed = [d for d in rows if d["event"] == "resume"]
    assert len(resumed) == 1 and resumed[0]["reason"] and resumed[0]["time"] == world.bar(k + 49).isoformat()
    tick_until(world, k + 51, has_position)                   # and the book trades again


def test_kill_true_in_the_config_is_the_same_switch(world):
    k = tick_until(world, K0, has_position)
    world.write_config(kill=True)
    hb = world.tick(world.bar(k + 1))
    st = world.book()["engine"]
    assert hb["killed"] and st["halted"] and st["halt_reason"] == "manual kill" and not st["positions"]
    assert world.book()["strategy"]["params"] == {**DONCHIAN.params, **PARAMS}      # same book, not a swap
    world.write_config(kill=False)
    hb = world.tick(world.bar(k + 2))
    assert not hb["killed"] and not world.book()["engine"]["halted"]


def test_kill_on_a_repeated_tick_is_committed_without_a_new_bar(world):
    k = tick_until(world, K0, has_position)
    rows_before = len(pd.read_csv(world.state / "equity_champion.csv"))
    (world.state / "KILL").write_text("")
    hb = world.tick(world.bar(k), minutes=30)                 # no new bar this hour
    st = world.book()["engine"]
    assert hb["killed"] and st["halted"] and st["last_time"] == world.bar(k).isoformat()
    assert all(p["exit_pending"] == "guardian" for p in st["positions"].values()) and st["positions"]
    assert len(pd.read_csv(world.state / "equity_champion.csv")) == rows_before
    world.tick(world.bar(k + 1))
    assert not world.book()["engine"]["positions"]


# ------------------------------------------------------------------- frozen feed
def test_frozen_feed_halts_every_book_and_recovers(world):
    world.write_config(challengers=[{"strategy": DON, "params": PARAMS}])
    k = tick_until(world, K0, has_position)
    held = sorted(world.book()["engine"]["positions"])
    for s in SYMBOLS:
        world.source.last_bar[s] = world.bar(k)               # the venue stops printing bars
    hb = world.tick(world.bar(k + 1))
    assert hb["ok"] and hb["feed"]["usable"] and not hb["feed"]["frozen"]
    assert [a["code"] for a in world.alerts()] == ["feed_late"]
    assert hb["books"]["champion"]["status"] == "idle" and hb["books"]["champion"]["lag_bars"] == 1
    assert hb["feed"]["feed_time"] == world.bar(k).isoformat()
    hb = world.tick(world.bar(k + 2))                         # 127 minutes without a fresh bar
    assert not hb["ok"] and hb["feed"]["frozen"] and world.alerts("feed_frozen")[0]["level"] == "critical"
    for book in ("champion", "challenger_1"):
        st = world.book(book)["engine"]
        assert st["halted"] and st["halt_reason"] == "frozen data feed" and not st["orders"]
        assert sorted(st["positions"]) == held and all(p["exit_pending"] == "guardian" for p in st["positions"].values())
        assert st["last_time"] == world.bar(k).isoformat()    # no bar was invented
    world.tick(world.bar(k + 3))
    world.source.last_bar.clear()                             # the feed comes back
    hb = world.tick(world.bar(k + 4))
    assert hb["ok"] and not hb["feed"]["frozen"] and hb["books"]["champion"]["lag_bars"] == 0
    assert len(world.alerts("missed_bars")) == 2              # one per book
    for book in ("champion", "challenger_1"):
        exits = [t for t in read_jsonl(world.state / f"ledger_{book}.jsonl") if t["reason"] == "guardian"]
        assert sorted(t["symbol"] for t in exits) == held
        assert {t["exit_time"] for t in exits} == {world.bar(k + 1).isoformat()}    # first bar after the freeze began
    # entries stay blocked until the UTC day after the last frozen tick, then come back by themselves
    last_frozen_day = (world.bar(k + 3) + HOUR).floor("D")
    kk = k + 5
    while world.bar(kk) < last_frozen_day + pd.Timedelta(days=1):
        hb = world.tick(world.bar(kk))
        assert hb["books"]["champion"]["halted"], world.bar(kk)
        kk += 1
    hb = world.tick(world.bar(kk))                            # first bar of the next UTC day
    assert not hb["books"]["champion"]["halted"]
    created = [d["time"] for d in read_jsonl(world.state / "decisions_champion.jsonl") if d["event"] == "order_created"]
    assert not [t for t in created if world.bar(k).isoformat() < t < world.bar(kk).isoformat()]


def test_a_required_symbol_that_keeps_failing_becomes_a_frozen_feed(world):
    k = tick_until(world, K0, has_position)
    world.source.fail = {ALTS[1]}
    hb = world.tick(world.bar(k + 1))
    assert hb["ok"] and not hb["feed"]["usable"] and hb["feed"]["failed"] == [ALTS[1]]
    assert hb["feed"]["feed_time"] == world.bar(k).isoformat()                 # keeps the last good value
    assert [a["code"] for a in world.alerts()] == ["feed_incomplete"]
    assert world.book()["engine"]["last_time"] == world.bar(k).isoformat() and not world.book()["engine"]["halted"]
    hb = world.tick(world.bar(k + 2))
    assert not hb["ok"] and hb["feed"]["frozen"] and not hb["feed"]["usable"]
    st = world.book()["engine"]
    assert st["halted"] and st["halt_reason"] == "frozen data feed" and st["last_time"] == world.bar(k).isoformat()
    world.source.fail = set()
    hb = world.tick(world.bar(k + 3))
    assert hb["ok"] and hb["feed"]["usable"] and hb["books"]["champion"]["lag_bars"] == 0
    assert not world.book()["engine"]["positions"]


def test_kill_switch_takes_over_an_existing_halt_so_its_release_resumes(world):
    run_ticks(world, range(K0, K0 + 3))
    for s in SYMBOLS:
        world.source.last_bar[s] = world.bar(K0 + 2)
    run_ticks(world, [K0 + 3, K0 + 4])                        # late, then frozen
    assert world.book()["engine"]["halt_reason"] == "frozen data feed"
    world.source.last_bar.clear()
    (world.state / "KILL").write_text("")
    run_ticks(world, [K0 + 5, K0 + 6])
    assert world.book()["engine"]["halt_reason"] == "manual kill"
    halts = [d["reason"] for d in read_jsonl(world.state / "decisions_champion.jsonl") if d["event"] == "guardian_halt"]
    assert halts == ["frozen data feed", "manual kill (takes over the halt: frozen data feed)"]   # logged once
    (world.state / "KILL").unlink()
    hb = world.tick(world.bar(K0 + 7))                        # still the same UTC day as the freeze
    assert not hb["books"]["champion"]["halted"] and world.bar(K0 + 7).day == world.bar(K0 + 3).day


# ------------------------------------------------------------------ failed symbol
def test_a_failed_required_symbol_stops_the_tick_and_the_bars_are_replayed(world):
    run_ticks(world, range(K0, K0 + 30))
    before = files(world)
    world.source.fail = {ALTS[0]}
    hb = world.tick(world.bar(K0 + 30))
    assert hb["ok"] and not hb["feed"]["usable"] and hb["feed"]["failed"] == [ALTS[0]]
    assert hb["books"]["champion"]["status"] == "idle" and hb["books"]["champion"]["lag_bars"] == 1
    after = files(world)
    assert {n: b for n, b in after.items() if n not in ("heartbeat.json", "alerts.jsonl")} == \
           {n: b for n, b in before.items() if n != "heartbeat.json"}
    a = world.alerts()
    assert [x["code"] for x in a] == ["feed_incomplete"] and a[0]["level"] == "warn"
    world.source.fail = set()
    run_ticks(world, range(K0 + 31, K0 + 60))
    assert_book_equals(world, "champion", reference(world, K0, K0 + 59))
    assert [x["code"] for x in world.alerts()] == ["feed_incomplete", "missed_bars"]


def test_a_failed_context_symbol_is_only_left_out(world):
    members = [s for s in SYMBOLS if s != ALTS[2]]
    world.write_universe({"2026-08": list(SYMBOLS), "2026-09": list(SYMBOLS), "2026-10": members, "2026-11": members})
    world.source.fail = {ALTS[2]}                             # in September's universe only: history, not tradable now
    k = 94 * 24                                               # 2026-10-03: the 300-bar window reaches into September
    hbs = run_ticks(world, range(k, k + 5))
    assert all(hb["ok"] and hb["feed"]["usable"] for hb in hbs)
    assert hbs[-1]["books"]["champion"]["status"] == "ok" and hbs[-1]["feed"]["failed"] == [ALTS[2]]
    assert {a["code"] for a in world.alerts()} == {"context_missing"}
    assert hbs[-1]["feed"]["symbols"] == 4


def test_clock_skew_stops_the_tick(world):
    run_ticks(world, range(K0, K0 + 3))
    world.source.skew = pd.Timedelta(seconds=45)
    hb = world.tick(world.bar(K0 + 3))
    assert not hb["ok"] and not hb["feed"]["usable"]
    assert [a["code"] for a in world.alerts()] == ["clock_skew"]
    assert world.book()["engine"]["last_time"] == world.bar(K0 + 2).isoformat()
    world.source.skew = pd.Timedelta(0)
    assert world.tick(world.bar(K0 + 4))["books"]["champion"]["lag_bars"] == 0


# --------------------------------------------------------------- failing strategy
class Boom(Strategy):
    name = "boom"
    params = {"n": 1}
    armed = True

    def intents(self, data, p):
        if self.armed:
            raise ZeroDivisionError("strategy bug")
        return {s: blank_intents(df.index) for s, df in data.items()}


def test_a_strategy_that_raises_leaves_the_other_books_running(world, monkeypatch):
    boom = Boom()
    mod = fake_strategy_module(monkeypatch, "zz_boom", boom)
    world.write_config(champion={"strategy": mod}, challengers=[{"strategy": DON, "params": PARAMS}])
    hbs = run_ticks(world, range(K0, K0 + 20))
    assert not hbs[-1]["ok"] and hbs[-1]["error"] is None
    assert hbs[-1]["books"]["champion"]["status"] == "error" and "ZeroDivisionError" in hbs[-1]["books"]["champion"]["detail"]
    assert hbs[-1]["books"]["challenger_1"]["status"] == "ok"
    assert not (world.state / "champion.json").exists() and not (world.state / "decisions_champion.jsonl").exists()
    errs = world.alerts("book_error")
    assert len(errs) == 20 and errs[0]["level"] == "critical" and errs[0]["book"] == "champion"
    assert "Traceback" in errs[0]["detail"]["traceback"] and "strategy bug" in errs[0]["detail"]["traceback"]
    assert_book_equals(world, "challenger_1", reference(world, K0, K0 + 19))


def test_a_book_whose_strategy_fails_for_a_while_is_untouched_then_replayed(world, monkeypatch):
    class Flaky(type(DONCHIAN)):
        name = "flaky_donchian"
        armed = False

        def intents(self, data, p):
            if self.armed:
                raise RuntimeError("temporary bug")
            return super().intents(data, p)

    flaky = Flaky()
    mod = fake_strategy_module(monkeypatch, "zz_flaky", flaky)
    world.write_config(champion={"strategy": mod, "params": PARAMS})
    run_ticks(world, range(K0, K0 + 30))
    before = files(world)
    flaky.armed = True
    hbs = run_ticks(world, range(K0 + 30, K0 + 33))
    assert all(not hb["ok"] and hb["books"]["champion"]["status"] == "error" for hb in hbs)
    assert hbs[-1]["books"]["champion"]["lag_bars"] == 3 and hbs[-1]["books"]["champion"]["equity"] is not None
    after = files(world)
    assert all(after[n] == before[n] for n in before if n not in ("heartbeat.json", "alerts.jsonl"))
    flaky.armed = False
    run_ticks(world, range(K0 + 33, K0 + 60))
    assert_book_equals(world, "champion", reference(world, K0, K0 + 59))


# ------------------------------------------------------------------ strategy swap
def test_strategy_swap_flattens_retires_and_starts_a_fresh_book(world):
    k = tick_until(world, K0, has_position)
    held = sorted(world.book()["engine"]["positions"])
    old_fp = world.book()["strategy"]
    new_params = {"n": 48, "atr_n": 12, "stop_atr": 2.0}
    world.write_config(champion={"strategy": DON, "params": new_params})
    hb = world.tick(world.bar(k + 1))
    # the old book sold everything at the open of bar k+1 and was retired; the new one started on that bar
    retired = list((world.state / "archive").glob("champion.*.swapped"))
    assert len(retired) == 1
    old = json.loads((retired[0] / "champion.json").read_text())
    assert old["strategy"] == old_fp and not old["engine"]["positions"] and not old["engine"]["orders"]
    exits = [t for t in read_jsonl(retired[0] / "ledger_champion.jsonl") if t["reason"] == "strategy_swap"]
    assert sorted(t["symbol"] for t in exits) == held
    assert {t["exit_time"] for t in exits} == {world.bar(k + 1).isoformat()}
    for t in exits:                                           # sold at the open, less slippage
        o = float(world.frames[t["symbol"]].loc[world.bar(k + 1), "open"])
        assert t["exit_price"] < o and t["exit_price"] == pytest.approx(o, rel=2e-3)
    assert pd.read_csv(retired[0] / "equity_champion.csv")["time"].iloc[-1] == world.bar(k + 1).isoformat()
    a = world.alerts("strategy_changed")
    assert len(a) == 1 and a[0]["level"] == "info" and a[0]["book"] == "champion" and hb["ok"]
    doc = world.book()
    assert doc["started_bar"] == world.bar(k + 1).isoformat()
    assert doc["strategy"]["params"] == {**DONCHIAN.params, **new_params}
    assert doc["engine"]["n_trades"] == 0 and not doc["engine"]["positions"]
    assert hb["books"]["champion"]["status"] == "ok"
    run_ticks(world, range(k + 2, k + 40))
    assert_book_equals(world, "champion", reference(world, k + 1, k + 39, new_params))


def test_swap_of_a_flat_book_and_swap_of_equity0(world):
    run_ticks(world, range(K0, K0 + 2))                       # flat so far
    assert not world.book()["engine"]["positions"]
    world.write_config(account={"equity0": 5000})
    hb = world.tick(world.bar(K0 + 2))
    assert hb["books"]["champion"]["equity"] == 5000.0 and world.book()["strategy"]["equity0"] == 5000.0
    assert world.book()["started_bar"] == world.bar(K0 + 2).isoformat()
    assert len(list((world.state / "archive").glob("champion.*.swapped"))) == 1
    assert [a["code"] for a in world.alerts()] == ["strategy_changed"]


def test_swap_waits_for_a_bar_before_closing_positions(world):
    k = tick_until(world, K0, has_position)
    world.write_config(champion={"strategy": DON, "params": {"n": 48}})
    hb = world.tick(world.bar(k), minutes=30)                 # no new bar yet: nothing can be sold
    assert hb["books"]["champion"]["status"] == "closing"
    st = world.book()["engine"]
    assert st["positions"] and all(p["exit_pending"] == "strategy_swap" for p in st["positions"].values())
    assert not st["orders"] and not list((world.state / "archive").glob("champion.*"))
    hb = world.tick(world.bar(k + 1))
    assert hb["books"]["champion"]["status"] == "ok" and world.book()["started_bar"] == world.bar(k + 1).isoformat()


def test_champion_set_to_null_closes_the_book_and_leaves_it_empty(world):
    k = tick_until(world, K0, has_position)
    world.write_config(champion=None)
    hb = world.tick(world.bar(k + 1))
    assert hb["ok"] and hb["books"]["champion"]["status"] == "empty"
    assert not (world.state / "champion.json").exists()
    retired = list((world.state / "archive").glob("champion.*.swapped"))
    assert len(retired) == 1 and not json.loads((retired[0] / "champion.json").read_text())["engine"]["positions"]


# ------------------------------------------------------------------ null champion
def test_null_champion_stays_flat_and_healthy(world):
    world.write_config(champion=None)
    hbs = run_ticks(world, range(K0, K0 + 3))
    for hb in hbs:
        assert hb["ok"] and hb["feed"]["usable"]
        assert {b["status"] for b in hb["books"].values()} == {"empty"}
        assert hb["books"]["champion"]["strategy"] is None and hb["books"]["champion"]["equity"] is None
    assert sorted(p.name for p in world.state.iterdir()) == ["heartbeat.json"]
    assert paper.status(world.state, now=world.bar(K0 + 2) + HOUR + pd.Timedelta(minutes=10))["healthy"]


def test_null_champion_with_a_challenger(world):
    world.write_config(champion=None, challengers=[{"strategy": DON, "params": PARAMS}])
    hbs = run_ticks(world, range(K0, K0 + 30))
    assert hbs[-1]["books"]["champion"]["status"] == "empty" and hbs[-1]["books"]["challenger_1"]["status"] == "ok"
    assert_book_equals(world, "challenger_1", reference(world, K0, K0 + 29))


def test_the_shipped_config_ticks_cleanly_with_nothing_to_trade(world):
    from pathlib import Path
    shipped = Path(__file__).resolve().parents[1] / "config" / "bot.yaml"
    world.source.now = world.bar(K0) + HOUR + pd.Timedelta(minutes=7)
    hb = paper.tick(shipped, world.state, now=world.source.now, source=world.source)
    assert hb["ok"] and {b["status"] for b in hb["books"].values()} == {"empty"}


# -------------------------------------------------------- month without universe
K_OCT_END = 123 * 24 - 1          # 2026-10-31 23:00


def test_a_month_missing_from_the_universe_is_waited_for_then_replayed(world):
    world.write_universe(MONTHS[:-1])                         # no 2026-11 yet
    first = K_OCT_END - 20
    hbs = run_ticks(world, range(first, K_OCT_END + 1))
    assert hbs[-1]["ok"] and world.alerts() == []
    world.write_config(challengers=[{"strategy": DON, "params": PARAMS}])     # a book added during the wait
    hbs = run_ticks(world, range(K_OCT_END + 1, K_OCT_END + 5))
    for hb in hbs:
        assert not hb["ok"] and hb["feed"]["usable"]
        assert hb["books"]["champion"]["status"] == "idle"
        assert hb["books"]["challenger_1"]["status"] == "waiting"
    assert hbs[-1]["books"]["champion"]["lag_bars"] == 4
    assert world.book()["engine"]["last_time"] == world.bar(K_OCT_END).isoformat()   # November is not traded blind
    stale = world.alerts("universe_stale")
    assert len(stale) == 4 and stale[0]["level"] == "critical" and "universe.json" in stale[0]["message"]
    assert not (world.state / "challenger_1.json").exists()
    world.write_universe(MONTHS)                              # someone ran the monthly refresh
    hb = world.tick(world.bar(K_OCT_END + 5))
    assert hb["ok"] and hb["books"]["champion"]["lag_bars"] == 0 and hb["books"]["challenger_1"]["status"] == "ok"
    run_ticks(world, range(K_OCT_END + 6, K_OCT_END + 30))
    assert_book_equals(world, "champion", reference(world, first, K_OCT_END + 29))
    assert world.book("challenger_1")["started_bar"] == world.bar(K_OCT_END + 5).isoformat()
    assert_book_equals(world, "challenger_1", reference(world, K_OCT_END + 5, K_OCT_END + 29))


def test_replay_across_a_month_boundary_requires_last_months_symbols(world):
    oct_members = list(SYMBOLS)
    nov_members = [s for s in SYMBOLS if s != ALTS[2]]
    world.write_universe({**{m: oct_members for m in MONTHS[:-1]}, "2026-11": nov_members})
    run_ticks(world, range(K_OCT_END - 10, K_OCT_END - 2))
    world.source.fail = {ALTS[2]}                             # needed to replay October, not for November alone
    hb = world.tick(world.bar(K_OCT_END + 3))
    assert not hb["feed"]["usable"] and hb["feed"]["failed"] == [ALTS[2]]
    world.source.fail = set()
    hb = world.tick(world.bar(K_OCT_END + 4))
    assert hb["books"]["champion"]["lag_bars"] == 0


# ---------------------------------------------------------------------- delisting
def test_a_held_symbol_that_stops_printing_bars_is_kept_then_closed_as_delisted(world):
    world.write_config(feed={"delist_after_bars": 3})
    k = tick_until(world, K0, lambda st: any(s in ALTS for s in st["positions"]))
    sym = next(s for s in world.book()["engine"]["positions"] if s in ALTS)
    world.source.last_bar[sym] = world.bar(k)
    hb = world.tick(world.bar(k + 1))                         # a held symbol's first silent hour is waited for:
    assert hb["ok"] and hb["feed"]["usable"] and not hb["feed"]["frozen"]       # the candle may only be late
    assert hb["books"]["champion"]["status"] == "idle" and hb["books"]["champion"]["lag_bars"] == 1
    late = world.alerts("feed_late")
    assert [a["symbol"] for a in late] == [sym] and late[0]["level"] == "warn" and not world.alerts("bar_missing")
    hb = world.tick(world.bar(k + 2))                         # still silent: both hours are now missing bars
    assert hb["books"]["champion"]["lag_bars"] == 0 and world.alerts("missed_bars")[-1]["detail"]["bars"] == 2
    pos = world.book()["engine"]["positions"]
    assert sym in pos and pos[sym]["last_price"] == pytest.approx(float(world.frames[sym].loc[world.bar(k), "close"]))
    gaps = [a for a in world.alerts("bar_missing") if a["symbol"] == sym]
    assert [a["detail"]["hours"] for a in gaps] == [2] and gaps[0]["level"] == "warn"
    world.tick(world.bar(k + 3))
    assert sym not in world.book()["engine"]["positions"]
    trade = [t for t in read_jsonl(world.state / "ledger_champion.jsonl") if t["symbol"] == sym][-1]
    assert trade["reason"] == "delisted" and trade["exit_time"] == world.bar(k + 3).isoformat()
    assert [a["symbol"] for a in world.alerts("symbol_delisted")] == [sym]
    hb = world.tick(world.bar(k + 4))                         # the dead symbol does not stop later ticks
    assert hb["feed"]["usable"] and hb["books"]["champion"]["lag_bars"] == 0


# ----------------------------------------------------------------- config errors
def test_invalid_config_alerts_and_fails_without_touching_books(world):
    run_ticks(world, range(K0, K0 + 3))
    before = files(world)
    world.config.write_text("mode: live\n")
    hb = world.tick(world.bar(K0 + 3))
    assert not hb["ok"] and "paper" in hb["error"] and hb["alerts"]["critical"] == 1
    assert [a["code"] for a in world.alerts()] == ["config_invalid"]
    after = files(world)
    assert all(after[n] == before[n] for n in before if n != "heartbeat.json")
    assert hb["feed"]["feed_time"] == world.bar(K0 + 2).isoformat()
    assert not paper.status(world.state, now=world.bar(K0 + 3) + HOUR + pd.Timedelta(minutes=8))["healthy"]


def test_an_error_outside_the_books_is_reported_and_never_raised(world, monkeypatch):
    run_ticks(world, range(K0, K0 + 3))

    def broken(*a, **k):
        raise OSError("disk on fire")
    monkeypatch.setattr(paper.feed, "prepare", broken)
    hb = world.tick(world.bar(K0 + 3))
    assert not hb["ok"] and "disk on fire" in hb["error"]
    a = world.alerts("tick_error")
    assert len(a) == 1 and a[0]["level"] == "critical" and "Traceback" in a[0]["detail"]["traceback"]
    assert json.loads((world.state / "heartbeat.json").read_text())["ok"] is False
    assert not (world.state / "tick.lock").exists()


# ------------------------------------------------------------- storage functions
def test_atomic_write_json_is_strict_and_leaves_no_temp_file(tmp_path):
    p = tmp_path / "x.json"
    paper.atomic_write_json(p, {"a": float("nan"), "b": np.float64(1.5), "c": np.int64(2), "d": [np.bool_(True)],
                                "e": float("inf")})
    assert json.loads(p.read_text()) == {"a": None, "b": 1.5, "c": 2, "d": [True], "e": None}
    paper.atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert [q.name for q in tmp_path.iterdir()] == ["x.json"]


def test_append_lines_returns_the_new_size(tmp_path):
    p = tmp_path / "log.jsonl"
    assert paper.append_lines(p, ['{"a": 1}', '{"a": 2}']) == 18
    assert paper.append_lines(p, ['{"a": 3}']) == 27 == p.stat().st_size
    assert p.read_text() == '{"a": 1}\n{"a": 2}\n{"a": 3}\n'


def test_read_log_joins_rotated_and_live_files_and_honours_since(world, monkeypatch):
    monkeypatch.setattr(paper, "MAX_LOG_MB", 3000 / 1024 / 1024)          # rotate above 3000 bytes
    run_ticks(world, range(K0, K0 + 120))
    rotated = sorted((world.state / "archive" / "rotated").glob("decisions_champion.*.jsonl"))
    assert len(rotated) >= 2
    assert all(3000 < p.stat().st_size < 9000 for p in rotated)
    assert world.book()["log_bytes"]["decisions"] == (world.state / "decisions_champion.jsonl").stat().st_size
    rows = paper.read_log(world.state, "decisions_champion")
    eng = reference(world, K0, K0 + 119)
    assert [(d["time"], d["symbol"], d["event"]) for d in rows if d["event"] != "book_started"] == \
           [(e["time"], e["symbol"], e["event"]) for e in eng.events]
    cut = world.bar(K0 + 100)
    late = paper.read_log(world.state, "decisions_champion", since=cut)
    assert late and len(late) < len(rows) and all(pd.Timestamp(d["time"]) >= cut for d in late)
    trades = paper.read_log(world.state, "ledger_champion", since=cut)
    assert all(pd.Timestamp(t["exit_time"]) >= cut for t in trades) and len(trades) < len(eng.trades)
    assert paper.read_log(world.state, "ledger_challenger_2") == []
    # the ledger and the equity file are never rotated
    assert not list((world.state / "archive" / "rotated").glob("ledger_*"))


def test_read_log_ignores_uncommitted_and_torn_lines(world):
    run_ticks(world, range(K0, K0 + 10))
    n = len(paper.read_log(world.state, "decisions_champion"))
    with open(world.state / "decisions_champion.jsonl", "ab") as f:
        f.write(b'{"time": "2026-09-23T00:00:00+00:00", "event": "entry"}\n{"torn": ')
    assert len(paper.read_log(world.state, "decisions_champion")) == n
    G_rows = [json.dumps({"tick_utc": "2026-09-22T09:07:00+00:00", "code": "x"}), '{"torn"']
    (world.state / "alerts.jsonl").write_text("\n".join(G_rows))
    assert [r["code"] for r in paper.read_log(world.state, "alerts")] == ["x"]


def test_retire_book_moves_logs_first_and_the_state_last(world, monkeypatch):
    run_ticks(world, range(K0, K0 + 5))
    moved = []
    real = os.replace

    def spy(src, dst):
        moved.append(os.path.basename(str(src)))
        return real(src, dst)
    monkeypatch.setattr(paper.os, "replace", spy)
    dest = paper.retire_book(world.state, "champion", "manual", "2026-09-22T13:07:00+00:00")
    assert dest == world.state / "archive" / "champion.20260922T130700Z.manual"
    assert moved[-1] == "champion.json" and set(moved[:-1]) >= {"decisions_champion.jsonl", "equity_champion.csv"}
    assert not (world.state / "champion.json").exists() and (dest / "champion.json").exists()
    again = paper.retire_book(world.state, "champion", "manual", "2026-09-22T13:07:00+00:00")
    assert again != dest and again.name.startswith("champion.20260922T130700Z.manual")


# ------------------------------------------------------------- status, loop, CLI
def test_status_reports_health_from_the_heartbeat(world, capsys):
    assert paper.status(world.state)["healthy"] is False and "no heartbeat" in paper.status(world.state)["why"]
    run_ticks(world, range(K0, K0 + 2))
    now = world.bar(K0 + 1) + HOUR + pd.Timedelta(minutes=30)
    st = paper.status(world.state, now=now)
    assert st["healthy"] and st["why"] == "ok" and st["heartbeat"]["mode"] == "paper"
    assert st["books"]["champion"]["status"] == "ok"
    late = paper.status(world.state, now=now + pd.Timedelta(hours=2))
    assert not late["healthy"] and "ago" in late["why"]
    world.source.skew = pd.Timedelta(minutes=5)
    world.tick(world.bar(K0 + 2))
    bad = paper.status(world.state, now=world.bar(K0 + 2) + HOUR + pd.Timedelta(minutes=9))
    assert not bad["healthy"] and "clock_skew" in bad["why"]
    assert paper.main(["status", "--state", str(world.state)]) == 1           # by now the heartbeat is old
    out = capsys.readouterr().out
    assert "NOT HEALTHY" in out and "champion" in out
    assert paper.main(["status", "--state", str(world.state), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["healthy"] is False


def test_cli_tick_exit_code_follows_the_heartbeat(world, monkeypatch):
    seen = {}

    def fake_tick(config_path, state_dir, now=None, source=None):
        seen.update(config=str(config_path), state=str(state_dir))
        return {"ok": seen.get("ok", True), "alerts": {"critical": 0}}
    monkeypatch.setattr(paper, "tick", fake_tick)
    assert paper.main(["tick", "--config", str(world.config), "--state", str(world.state)]) == 0
    assert seen["config"] == str(world.config) and seen["state"] == str(world.state)
    seen["ok"] = False
    assert paper.main(["tick", "--config", str(world.config), "--state", str(world.state)]) == 1
    assert paper.CONFIG == "config/bot.yaml" and paper.STATE == "state"


def test_loop_ticks_then_sleeps_to_the_next_hour_plus_settle(world, monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr(paper, "tick", lambda c, s, now=None, source=None: calls.append((str(c), str(s))) or {"ok": True})
    monkeypatch.setattr(paper.time, "sleep", lambda s: sleeps.append(s))
    clock = iter([pd.Timestamp("2026-09-22 10:02:40", tz="UTC"), pd.Timestamp("2026-09-22 11:00:05", tz="UTC")])
    monkeypatch.setattr(paper, "_now", lambda: next(clock))
    paper.loop(world.config, world.state, source=world.source, max_ticks=3)
    assert len(calls) == 3 and calls[0] == (str(world.config), str(world.state))
    # 10:02:40 -> next wake 11:02:30; 11:00:05 -> 11:02:30 (settle 120 s + 30 s after the hour)
    assert sleeps == [pytest.approx(59 * 60 + 50), pytest.approx(145)]
