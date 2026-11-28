"""Adversarial review of the paper bot: crash safety, idempotency and state.

Tests marked  # DEFECT: <id>  FAIL on the code as reviewed; each one pins a defect in the review report.
The other tests pass: they pin behaviour the review checked and found sound.
No network (fake source, sockets blocked) and nothing is written outside tmp_path.
"""
from __future__ import annotations

import json
import os
import random

import numpy as np
import pandas as pd
import pytest

from desk.bot import feed as F
from desk.bot import paper
from desk.engine.core import Costs, Engine, Risk, attach
from desk.strategies.base import Strategy, blank_intents
from test_bot_fakes import (ALTS, HOUR, PARAMS, SYMBOLS, World, fake_strategy_module,  # noqa: F401
                            no_network, read_jsonl, world)

pytestmark = pytest.mark.usefixtures("no_network")
K0 = 2000
DON = "desk.strategies.ref_donchian"


# ---------------------------------------------------------------------- helpers
def has_position(st) -> bool:
    return bool(st["positions"])


def tick_until(w, k: int, cond, limit: int = 400) -> int:
    for kk in range(k, k + limit):
        w.tick(w.bar(kk))
        if cond(w.book()["engine"]):
            return kk
    raise AssertionError("the fake market never produced the situation this test needs")


def twin_of(w) -> World:
    """A second installation on the same fake market (same bars, own config and state directory)."""
    root = w.root / "twin"
    root.mkdir()
    return World(root)


def trades(state_dir, book: str = "champion") -> list[tuple]:
    return [(t["symbol"], t["entry_time"], t["exit_time"], t["reason"], round(t["pnl"], 6))
            for t in read_jsonl(state_dir / f"ledger_{book}.jsonl")]


class Crash(BaseException):
    """The process dying: not an Exception, so nothing in the bot may catch it."""


class Rich(Strategy):
    """Limit entries that stay working 3 bars, take-profits, trailing stops, signal exits, a 9-bar time stop."""
    name = "review_rich"
    valid_bars = 3
    max_hold = 9
    params = {"n": 6}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            hi, lo = c.rolling(p["n"]).max().shift(1), c.rolling(p["n"]).min().shift(1)
            rng = (df["high"] - df["low"]).rolling(6).mean()
            long, short = (c > hi) & rng.notna(), (c < lo) & rng.notna()
            it["side"] = np.where(long, 1, np.where(short, -1, 0)).astype(np.int8)
            it["limit"] = np.where(long, c - 0.5 * rng, np.where(short, c + 0.5 * rng, np.nan))
            it["stop"] = np.where(long, c - 3.5 * rng, np.where(short, c + 3.5 * rng, np.nan))
            it["tp"] = np.where(long, c + 5 * rng, np.where(short, c - 5 * rng, np.nan))
            it["trail"] = c - 3.0 * rng
            it["exit"] = (c.pct_change(3).abs() > 0.03).to_numpy()
            out[s] = it
        return out


RICH = Rich()
TIGHT = {"daily_loss_limit": 0.004, "max_consec_losses": 2}       # so Guardian halts happen often


def rich_world(w, monkeypatch) -> None:
    w.write_config(champion={"strategy": fake_strategy_module(monkeypatch, "s_review_rich", RICH)}, guardian=TIGHT)


def rich_reference(w, first_k: int, last_k: int) -> Engine:
    last = w.bar(last_k)
    data, _, _ = F.prepare({s: df[df.index <= last] for s, df in w.frames.items()}, last, 72)
    base = F.build_base(data, last)
    eng = Engine(Costs(), Risk(**TIGHT), RICH.valid_bars, RICH.max_hold, log_events=True)
    eng.run(attach(base, RICH.intents(data, RICH.params)), int(base.index.get_loc(w.bar(first_k))), len(base.index))
    return eng


def without_tick(lines: list[str]) -> list[dict]:
    rows = [json.loads(line) for line in lines]
    for r in rows:
        r.pop("tick_utc", None)
    return rows


# =========================================================================================
# DEFECTS (these tests fail on the reviewed code)
# =========================================================================================

# DEFECT: S1  (high) a held symbol whose requests keep failing stops the whole bot for good
def test_S1_a_held_symbol_that_can_no_longer_be_fetched_must_not_stop_the_bot_forever(world):
    """The spec promises that a held symbol which goes quiet is kept for `delist_after_bars` hours and then
    closed as `delisted`. That only works while the venue still ANSWERS for the symbol. If its requests fail
    instead (a delisted contract answering 400/404 on any of the 17 calls: KrakenSource fails the symbol on a
    single failed analytics or funding request), the symbol stays `required` because it is held, the feed is
    never usable again, no book ever processes another bar, the position is never closed, and every book stays
    halted (`frozen data feed`) until someone edits the state file by hand."""
    world.write_config(feed={"delist_after_bars": 3})
    k = tick_until(world, K0, lambda st: any(s in ALTS for s in st["positions"]))
    sym = next(s for s in world.book()["engine"]["positions"] if s in ALTS)
    world.source.fail = {sym}                                   # from now on the venue answers with an error
    for kk in range(k + 1, k + 13):                             # 12 hours: four times delist_after_bars
        hb = world.tick(world.bar(kk))
    st = world.book()["engine"]
    assert sym not in st["positions"], "the dead symbol's position is still open after 4x delist_after_bars"
    assert st["last_time"] > world.bar(k).isoformat(), "the book has not processed a single bar since the outage began"
    assert hb["feed"]["usable"]


# DEFECT: S2  (medium) a kill or strategy swap seen by a catch-up tick is filled at a price from hours earlier
@pytest.mark.parametrize("action", ["kill", "swap"])
def test_S2_kill_or_swap_after_missed_hours_gives_the_same_result_as_hourly_ticks(world, action):
    """Spec, failure table: missed hours are replayed 'in order ... same result as hourly ticks'. But the halt
    (step 6b) and the swap (6c) are applied BEFORE the missed bars are replayed, so the positions are sold at
    the open of the first MISSED bar: a price from before the owner asked, chosen with hindsight. After an
    11-hour scheduler gap the paper book exits 11 hours in the past and skips everything in between."""
    gap = 12
    hourly, late = world, twin_of(world)
    k = tick_until(hourly, K0, has_position)
    for kk in range(K0, k + 1):
        late.tick(late.bar(kk))
    assert trades(hourly.state) == trades(late.state) and late.book()["engine"]["positions"]
    for kk in range(k + 1, k + gap):                            # `hourly` is woken every hour, `late` is not
        hourly.tick(hourly.bar(kk))
    for w in (hourly, late):                                    # then the owner acts, and the next tick sees it
        if action == "kill":
            (w.state / "KILL").write_text("")
        else:
            w.write_config(champion={"strategy": DON, "params": {**PARAMS, "n": 48}})
        w.tick(w.bar(k + gap))

    def ledger(w):
        if action == "kill":
            return trades(w.state)
        return trades(next((w.state / "archive").glob("champion.*.swapped")))
    reason = "guardian" if action == "kill" else "strategy_swap"
    forced = [t for t in ledger(late) if t[3] == reason]
    assert forced and all(t[2] == late.bar(k + gap).isoformat() for t in forced), \
        f"positions were sold at {forced[0][2]}, hours before the {action} was requested ({late.bar(k + gap).isoformat()})"
    assert ledger(late) == ledger(hourly)


# DEFECT: S3  (medium) one failed fetch on the first tick after a scheduler gap is called a frozen feed
def test_S3_one_failed_fetch_after_a_scheduler_gap_is_not_a_frozen_feed(world):
    """The frozen rule measures from the previous heartbeat's feed_time. When the scheduler did not fire for a
    few hours (GitHub cron does that) that time is old although the feed was never seen failing. A single
    transient failure of ONE symbol on the first tick back is then `feed_frozen`: every book is halted, all
    orders are cancelled, all positions are sold (at the first missed bar's open, see S2) and entries stay
    blocked until the next UTC day. The same happens when a single hourly run starts more than 23 minutes
    late and one request fails."""
    k = tick_until(world, K0, has_position)
    held = sorted(world.book()["engine"]["positions"])
    world.source.fail = {ALTS[1]}                               # one symbol, one tick
    hb = world.tick(world.bar(k + 6))                           # first tick after 5 silent hours
    assert not hb["feed"]["usable"]
    assert not hb["feed"]["frozen"], "the bot has seen ONE failed fetch; it was not running during the other hours"
    st = world.book()["engine"]
    assert not st["halted"] and sorted(st["positions"]) == held
    assert all(not p["exit_pending"] for p in st["positions"].values())


# DEFECT: S4  (low) promoting one challenger wipes the other challenger's paper record
def test_S4_promoting_a_challenger_keeps_the_other_challengers_record(world):
    """Books are keyed by position in the `challengers` list. The edit the runbook describes ('move the
    challenger's entry to champion:') shifts the remaining challenger from slot 2 to slot 1, so its untouched
    strategy is closed, archived and restarted flat: its winning-day count starts again from zero."""
    a = {"strategy": DON, "params": {**PARAMS, "n": 36}}
    b = {"strategy": DON, "params": {**PARAMS, "n": 48}}
    world.write_config(challengers=[a, b])
    for kk in range(K0, K0 + 30):
        world.tick(world.bar(kk))
    b_book = world.book("challenger_2")
    assert b_book["strategy"]["params"]["n"] == 48 and b_book["started_bar"] == world.bar(K0).isoformat()
    world.write_config(champion=a, challengers=[b])             # promote A; B was not touched
    world.tick(world.bar(K0 + 30))
    world.tick(world.bar(K0 + 31))
    live = [world.book(n) for n in ("challenger_1", "challenger_2") if (world.state / f"{n}.json").exists()]
    b_now = [d for d in live if d["strategy"]["params"]["n"] == 48]
    assert len(b_now) == 1
    assert b_now[0]["started_bar"] == world.bar(K0).isoformat(), \
        "challenger B's book was retired and restarted flat although its strategy did not change"


# DEFECT: S5  (low) a wrong machine clock destroys or halts books before the clock is checked
def test_S5_a_clock_far_ahead_does_not_retire_the_books(world):
    """Step 3 retires books 'older than max_catchup_bars' using this machine's clock; the clock is only
    compared with the venue's in step 4. With the clock ~100 days ahead the book (open position included) is
    archived as too_old and restarts flat, and only then does the tick report clock_skew."""
    k = tick_until(world, K0, has_position)
    before = world.book()
    right = world.bar(k) + HOUR + pd.Timedelta(minutes=7)
    world.source.now = right                                    # the venue's clock is right, ours is not
    paper.tick(world.config, world.state, now=right + pd.Timedelta(days=100), source=world.source)
    assert "clock_skew" in [a["code"] for a in world.alerts()]
    assert (world.state / "champion.json").exists(), "the book was archived on the word of a wrong clock"
    assert world.book()["engine"] == before["engine"] and world.book()["started_bar"] == before["started_bar"]


# DEFECT: S5
def test_S5_a_clock_three_hours_ahead_does_not_halt_and_flatten_the_books(world):
    """`clock_skew` says 'nothing is processed', but the same wrong clock is then used to age the feed:
    three hours ahead reads as a frozen feed, so every book is halted and its positions are flagged for sale."""
    k = tick_until(world, K0, has_position)
    before = world.book()["engine"]
    right = world.bar(k) + HOUR + pd.Timedelta(minutes=7)
    world.source.now = right
    hb = paper.tick(world.config, world.state, now=right + pd.Timedelta(hours=3), source=world.source)
    assert "clock_skew" in [a["code"] for a in world.alerts()] and not hb["feed"]["usable"]
    assert world.book()["engine"] == before, "a book was changed by a tick whose clock was known to be wrong"


# =========================================================================================
# VERIFIED BEHAVIOUR (these tests pass)
# =========================================================================================

def test_hourly_ticks_equal_one_engine_run_with_limits_targets_trails_time_stops_and_halts(world, monkeypatch):
    rich_world(world, monkeypatch)
    n = 150
    for k in range(K0, K0 + n):
        assert world.tick(world.bar(k))["books"]["champion"]["status"] == "ok"
    eng = rich_reference(world, K0, K0 + n - 1)
    kinds = {e["event"] for e in eng.events}
    reasons = {t["reason"] for t in eng.trades}
    assert {"order_created", "order_expired", "entry", "exit", "guardian_halt", "signal_blocked"} <= kinds
    assert {"stop", "time", "guardian"} <= reasons and len(eng.trades) >= 20     # the comparison is not vacuous
    ledger = read_jsonl(world.state / "ledger_champion.jsonl")
    assert [(t["symbol"], t["entry_time"], t["exit_time"], t["reason"]) for t in ledger] == \
           [(t["symbol"], t["entry_time"], t["exit_time"], t["reason"]) for t in eng.trades]
    assert [t["pnl"] for t in ledger] == pytest.approx([t["pnl"] for t in eng.trades], rel=1e-9, abs=1e-9)
    decisions = [d for d in read_jsonl(world.state / "decisions_champion.jsonl") if d["event"] != "book_started"]
    assert [(d["time"], d["symbol"], d["event"]) for d in decisions] == \
           [(e["time"], e["symbol"], e["event"]) for e in eng.events]
    st = world.book()["engine"]
    assert st["equity"] == pytest.approx(eng.state.equity, abs=1e-6)
    assert (st["halted"], st["halt_day"], st["consec_losses"]) == \
           (eng.state.halted, eng.state.halt_day, eng.state.consec_losses)
    assert sorted(st["orders"]) == sorted(eng.state.orders) and sorted(st["positions"]) == sorted(eng.state.positions)


def test_catch_up_ticks_equal_hourly_ticks_with_orders_stops_and_halts_in_flight(world, monkeypatch):
    hourly, late = world, twin_of(world)
    rich_world(hourly, monkeypatch)
    rich_world(late, monkeypatch)
    n = 150
    for k in range(K0, K0 + n):
        hourly.tick(hourly.bar(k))
    for k in list(range(K0, K0 + 20)) + [K0 + 57, K0 + 58, K0 + 110, K0 + n - 1]:      # gaps of 37, 52 and 39 hours
        late.tick(late.bar(k))
    for name in ("ledger_champion.jsonl", "decisions_champion.jsonl"):
        assert without_tick((late.state / name).read_text().splitlines()) == \
               without_tick((hourly.state / name).read_text().splitlines()), name
    rows = [[line.rsplit(",", 1)[0] for line in (w.state / "equity_champion.csv").read_text().splitlines()]
            for w in (hourly, late)]
    assert rows[0] == rows[1]
    assert late.book()["engine"] == hourly.book()["engine"]


def test_a_clock_that_jumps_back_changes_nothing(world):
    k = tick_until(world, K0, has_position)
    before = {p.name: p.read_bytes() for p in world.state.iterdir() if p.is_file() and p.name != "heartbeat.json"}
    hb = world.tick(world.bar(k - 30))                          # now is 30 hours before the book's last bar
    assert hb["books"]["champion"]["status"] == "idle" and hb["books"]["champion"]["lag_bars"] == 0
    after = {p.name: p.read_bytes() for p in world.state.iterdir() if p.is_file() and p.name != "heartbeat.json"}
    assert after == before and not (world.state / "tick.lock").exists()


def test_a_crash_after_one_book_committed_leaves_the_other_to_be_replayed(world, monkeypatch):
    other = {"strategy": DON, "params": {**PARAMS, "n": 36}}
    world.write_config(challengers=[other])
    for k in range(K0, K0 + 40):
        world.tick(world.bar(k))
    real = paper.atomic_write_json

    def dying(path, obj):
        if os.path.basename(str(path)) == "challenger_1.json":
            raise Crash()
        return real(path, obj)
    monkeypatch.setattr(paper, "atomic_write_json", dying)
    with pytest.raises(Crash):
        world.tick(world.bar(K0 + 40))
    monkeypatch.setattr(paper, "atomic_write_json", real)
    assert world.book()["engine"]["last_time"] == world.bar(K0 + 40).isoformat()            # champion committed
    assert world.book("challenger_1")["engine"]["last_time"] == world.bar(K0 + 39).isoformat()
    assert not (world.state / "tick.lock").exists()
    world.tick(world.bar(K0 + 40), minutes=20)                  # the scheduler fires again in the same hour
    for book in ("champion", "challenger_1"):
        doc = world.book(book)
        assert doc["engine"]["last_time"] == world.bar(K0 + 40).isoformat()
        eq = pd.read_csv(world.state / f"equity_{book}.csv")
        assert eq["time"].is_unique and len(eq) == 41
        for kind, name in (("decisions", f"decisions_{book}.jsonl"), ("ledger", f"ledger_{book}.jsonl"),
                           ("equity", f"equity_{book}.csv")):
            size = (world.state / name).stat().st_size if (world.state / name).exists() else 0
            assert doc["log_bytes"][kind] == size
    assert [a["book"] for a in world.alerts("log_rollback")] == ["challenger_1"]


def test_a_crash_half_way_through_retiring_a_book_recovers_on_the_next_tick(world, monkeypatch):
    k = tick_until(world, K0, has_position)
    world.write_config(champion={"strategy": DON, "params": {**PARAMS, "n": 48}})
    real = os.replace

    def dying(src, dst):
        if os.path.basename(str(src)) == "champion.json" and "archive" in str(dst):
            raise Crash()                                       # the logs are archived, the state file is not
        return real(src, dst)
    monkeypatch.setattr(paper.os, "replace", dying)
    with pytest.raises(Crash):
        world.tick(world.bar(k + 1))
    monkeypatch.setattr(paper.os, "replace", real)
    hb = world.tick(world.bar(k + 2))
    assert hb["ok"] and hb["error"] is None and hb["books"]["champion"]["status"] == "ok"
    doc = world.book()
    assert doc["strategy"]["params"]["n"] == 48 and doc["started_bar"] == world.bar(k + 2).isoformat()
    assert len(pd.read_csv(world.state / "equity_champion.csv")) == 1
    archived = sorted(q.name for p in (world.state / "archive").glob("champion.*.swapped*") for q in p.iterdir())
    assert archived == ["champion.json", "decisions_champion.jsonl", "equity_champion.csv", "ledger_champion.jsonl"]


def check_books(w, tag) -> None:
    """What must hold after ANY sequence of ticks and crashes, for the committed part of each book's files."""
    for book in ("champion", "challenger_1"):
        path = w.state / f"{book}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        eng = doc["engine"]
        eq_path = w.state / f"equity_{book}.csv"
        if eq_path.exists():
            lines = eq_path.read_bytes()[:doc["log_bytes"]["equity"]].decode().splitlines()
            times = [line.split(",")[0] for line in lines[1:]]
            idx = pd.to_datetime(times)
            assert len(times) == len(set(times)), (tag, book, "an equity row was written twice")
            assert ((idx[1:] - idx[:-1]) == HOUR).all(), (tag, book, "a bar is missing from the equity log")
            if times:
                assert times[0] == doc["started_bar"] and times[-1] == eng["last_time"], (tag, book)
        ledger_path = w.state / f"ledger_{book}.jsonl"
        if ledger_path.exists():
            rows = [json.loads(x) for x in ledger_path.read_bytes()[:doc["log_bytes"]["ledger"]].decode().splitlines()]
            keys = [(r["symbol"], r["entry_time"], r["exit_time"]) for r in rows]
            assert len(keys) == len(set(keys)), (tag, book, "a trade was logged twice")
            assert len(rows) == eng["n_trades"], (tag, book, "ledger and state disagree on the number of trades")
            if not eng["positions"]:
                assert eng["equity"] == pytest.approx(doc["strategy"]["equity0"] + sum(r["pnl"] for r in rows), abs=1e-6)


def test_random_crashes_double_ticks_gaps_outages_kills_and_swaps_never_corrupt_a_book(world, monkeypatch):
    rng = random.Random(4)
    challenger = {"strategy": DON, "params": {**PARAMS, "n": 36}}
    world.write_config(challengers=[challenger])
    real_write, real_append, real_replace = paper.atomic_write_json, paper.append_lines, os.replace
    armed = {"what": None, "n": 0}

    def fire(what: str) -> None:
        if armed["what"] == what:
            armed["n"] -= 1
            if armed["n"] <= 0:
                armed["what"] = None
                raise Crash()

    def write(path, obj):
        fire("state" if not str(path).endswith("heartbeat.json") else "heartbeat")
        return real_write(path, obj)

    def append(path, lines):
        fire("append")
        return real_append(path, lines)

    def replace(src, dst):
        if "archive" in str(dst):
            fire("archive")
        return real_replace(src, dst)
    monkeypatch.setattr(paper, "atomic_write_json", write)
    monkeypatch.setattr(paper, "append_lines", append)
    monkeypatch.setattr(paper.os, "replace", replace)
    k, swaps, crashes = K0, 0, 0
    for step in range(120):
        ev, minutes = rng.random(), 7.0
        if ev < 0.12:
            armed.update(what=rng.choice(["state", "append", "heartbeat", "archive"]), n=rng.randint(1, 3))
        elif ev < 0.18:
            k += rng.randint(1, 30)                             # the scheduler did not fire
        elif ev < 0.24:
            k, minutes = k - 1, rng.choice([1.0, 20.0, 40.0])   # a second tick in the same hour
        elif ev < 0.30:
            world.source.fail = {rng.choice(SYMBOLS)}
        elif ev < 0.36:
            (world.state / "KILL").write_text("")
        elif ev < 0.42:
            swaps += 1
            world.write_config(champion={"strategy": DON, "params": {**PARAMS, "n": 24 + swaps}},
                               challengers=[challenger])
        try:
            hb = world.tick(world.bar(k), minutes=minutes)
            assert hb.get("error") is None, (step, hb.get("error"))
        except Crash:
            crashes += 1
        armed["what"] = None
        assert not (world.state / "tick.lock").exists()
        check_books(world, (step, k))
        world.source.fail = set()
        if rng.random() < 0.5:
            (world.state / "KILL").unlink(missing_ok=True)
        k += 1
    codes = {a["code"] for a in world.alerts()}
    assert crashes >= 3 and "log_rollback" in codes and "strategy_changed" in codes
    assert not codes & {"book_error", "tick_error", "state_unreadable"}
