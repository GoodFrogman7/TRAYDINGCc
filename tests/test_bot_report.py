"""report.py: 24-hour / weekly summary, promotion check, paper next to backtest."""
from __future__ import annotations

import json
import re
import shutil

import pandas as pd
import pytest

from desk.bot import paper, report
from desk.data import store
from test_bot_fakes import HOUR, World, no_network, read_jsonl  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")
K0 = 2000
DON = "desk.strategies.ref_donchian"


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


# ------------------------------------------------- hand-made books for promotion
def make_book(state_dir, name: str, day_closes: list[float], first_day="2026-11-01", equity0=10000.0,
              strategy="s_demo", extra_today: float | None = None) -> None:
    """A state file and equity log whose last equity of each UTC day is `day_closes`
    (plus, optionally, a few hours of a still-running day)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    start = ts(first_day)
    rows, eq = ["time,equity,gross,tick_utc"], equity0
    for d, close in enumerate(day_closes):
        for h in range(24):
            eq = close if h == 23 else eq                    # the day's move lands on its last bar
            when = start + pd.Timedelta(days=d, hours=h)
            rows.append(f"{when.isoformat()},{eq!r},0.0,{(when + HOUR).isoformat()}")
    last = start + pd.Timedelta(days=len(day_closes)) - HOUR
    if extra_today is not None:
        for h in range(5):
            last = start + pd.Timedelta(days=len(day_closes), hours=h)
            eq = extra_today
            rows.append(f"{last.isoformat()},{eq!r},0.0,{(last + HOUR).isoformat()}")
    text = "\n".join(rows) + "\n"
    (state_dir / f"equity_{name}.csv").write_text(text)
    engine = {"cash": eq, "equity": eq, "positions": {}, "orders": {}, "day": 1, "day_start_equity": eq,
              "consec_losses": 0, "halted": False, "halt_reason": "", "halt_day": -1,
              "last_time": last.isoformat(), "n_trades": 0}
    paper.atomic_write_json(state_dir / f"{name}.json", {
        "schema": 1, "book": name, "started_bar": start.isoformat(), "updated_utc": (last + HOUR).isoformat(),
        "engine": engine,
        "strategy": {"module": f"desk.strategies.{strategy}", "name": strategy, "params": {}, "valid_bars": 1,
                     "max_hold": 0, "equity0": equity0},
        "log_bytes": {"decisions": 0, "ledger": 0, "equity": len(text.encode())}})


UP7 = [10010, 10020, 10030, 10040, 10050, 10060, 10070]


def test_challenger_is_ready_after_seven_winning_days_that_beat_the_champion(tmp_path):
    make_book(tmp_path, "champion", [10005, 10010, 10015, 10020, 10025, 10030, 10035], strategy="s_champ")
    make_book(tmp_path, "challenger_1", UP7, strategy="s_fast")
    make_book(tmp_path, "challenger_2", [10010, 10020, 10030, 10040, 10050, 10060, 10055], strategy="s_slow")
    p = report.promotion(tmp_path, now=ts("2026-11-08 00:10"))
    assert p["days_required"] == 7 and p["champion"]["strategy"] == "s_champ"
    c1, c2 = p["challengers"]["challenger_1"], p["challengers"]["challenger_2"]
    assert c1["strategy"] == "s_fast" and c1["winning_days"] == 7 and c1["days"] == 7
    assert c1["pnl"] == pytest.approx(70.0) and c1["champion_pnl_same_days"] == pytest.approx(35.0)
    assert c1["ready"] is True
    assert c2["winning_days"] == 6 and c2["ready"] is False and "6 of 7" in c2["why"]


def test_promotion_needs_positive_pnl_and_must_beat_the_champion(tmp_path):
    make_book(tmp_path, "champion", [10020, 10040, 10060, 10080, 10100, 10120, 10140, 10160])
    # seven small winning days after one big losing day: still under water
    make_book(tmp_path, "challenger_1", [9000, 9010, 9020, 9030, 9040, 9050, 9060, 9070])
    # seven winning days, in profit, but the champion made more over the same days
    make_book(tmp_path, "challenger_2", [10010, 10020, 10030, 10040, 10050, 10060, 10070], first_day="2026-11-02")
    p = report.promotion(tmp_path, now=ts("2026-11-09 00:10"))
    c1, c2 = p["challengers"]["challenger_1"], p["challengers"]["challenger_2"]
    assert c1["winning_days"] == 7 and c1["pnl"] == pytest.approx(-930.0)
    assert c1["ready"] is False and "not positive" in c1["why"]
    assert c2["winning_days"] == 7 and c2["pnl"] == pytest.approx(70.0)
    assert c2["champion_pnl_same_days"] == pytest.approx(140.0)       # from 2026-11-02 on: 10160 - 10020
    assert c2["ready"] is False and "champion" in c2["why"]


def test_promotion_ignores_the_unfinished_day_and_handles_missing_books(tmp_path):
    make_book(tmp_path, "challenger_1", UP7[:6], extra_today=10500.0)        # today is up, but not over
    p = report.promotion(tmp_path, now=ts("2026-11-07 05:10"))
    c1 = p["challengers"]["challenger_1"]
    assert c1["winning_days"] == 6 and c1["days"] == 6 and c1["ready"] is False
    assert c1["pnl"] == pytest.approx(500.0)
    assert p["champion"] is None and c1["champion_pnl_same_days"] == 0.0
    assert set(p["challengers"]) == {"challenger_1"}
    done = report.promotion(tmp_path, now=ts("2026-11-08 00:10"))["challengers"]["challenger_1"]
    assert done["winning_days"] == 7 and done["ready"] is True              # no champion to beat
    assert report.promotion(tmp_path, days=8, now=ts("2026-11-08 00:10"))["challengers"]["challenger_1"]["ready"] is False
    assert report.promotion(tmp_path / "nothing")["challengers"] == {}


# -------------------------------------------------------------- the whole report
def test_report_on_an_empty_state_directory_says_the_bot_has_not_run(tmp_path):
    r = report.build_report(tmp_path / "state", now=ts("2026-11-18 14:00"), results_dir=tmp_path / "none")
    assert r["health"]["healthy"] is False and "no heartbeat" in r["health"]["why"]
    assert r["books"] == {"champion": None, "challenger_1": None, "challenger_2": None}
    assert r["alerts"] == {} and r["mode"] == "paper"
    text = report.render(r)
    assert "PAPER" in text and "NOT HEALTHY" in text and "no heartbeat" in text


@pytest.fixture(scope="module")
def traded(tmp_path_factory):
    """Two books run for 80 hours with a feed hiccup, plus a results file to compare against.
    Built once for this module; tests that change the state work on a copy."""
    tmp = tmp_path_factory.mktemp("traded")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(store, "DATA", tmp / "data")
        store.universe.cache_clear()
        w = World(tmp)
        w.write_config(challengers=[{"strategy": DON, "params": {"n": 12, "atr_n": 12, "stop_atr": 1.5}}])
        for k in range(K0, K0 + 80):
            if k == K0 + 70:
                w.source.fail = {"PF_AAAUSD"}
            w.tick(w.bar(k))
            w.source.fail = set()
        results = tmp / "results"
        results.mkdir()
        (results / "ref_donchian.json").write_text(json.dumps({
            "name": "ref_donchian", "default_validation": {"total_return": 0.5, "years": 1.0},
            "wf_validation": {"years": 1.374, "total_return": -0.159, "n_trades": 652, "win_rate": 0.302,
                              "avg_r": -0.049, "max_dd": -0.41, "sharpe": -0.4}}))
        w.results = results
        w.now = w.bar(K0 + 79) + HOUR + pd.Timedelta(minutes=20)
        yield w
    store.universe.cache_clear()            # the next reader must see the real file again


def test_report_numbers_come_from_the_books_files(traded):
    w = traded
    r = report.build_report(w.state, hours=24, now=w.now, results_dir=w.results)
    since = w.now - pd.Timedelta(hours=24)
    assert r["hours"] == 24 and r["since_utc"] == since.isoformat() and r["generated_utc"] == w.now.isoformat()
    assert r["health"]["healthy"] is True and r["health"]["killed"] is False
    assert r["health"]["last_tick_utc"] == (w.bar(K0 + 79) + HOUR + pd.Timedelta(minutes=7)).isoformat()
    assert r["books"]["challenger_2"] is None
    for name in ("champion", "challenger_1"):
        b, doc = r["books"][name], w.book(name)
        ledger = read_jsonl(w.state / f"ledger_{name}.jsonl")
        eq = pd.read_csv(w.state / f"equity_{name}.csv")
        eq["time"] = pd.to_datetime(eq["time"])
        assert b["strategy"] == "ref_donchian" and b["started_bar"] == w.bar(K0).isoformat()
        assert b["equity"] == pytest.approx(doc["engine"]["equity"]) and b["equity0"] == 10000.0
        assert b["pnl_total"] == pytest.approx(doc["engine"]["equity"] - 10000.0)
        before = eq[eq["time"] + HOUR <= since]["equity"].iloc[-1]       # the last bar that had closed by then
        assert b["pnl_period"] == pytest.approx(doc["engine"]["equity"] - before)
        recent = [t for t in ledger if pd.Timestamp(t["exit_time"]) >= since]
        assert [t["exit_time"] for t in b["trades"]] == [t["exit_time"] for t in recent] and recent
        assert all(t["reason"] and "pnl" in t and "symbol" in t and "r" in t for t in b["trades"])
        assert b["trades_pnl"] == pytest.approx(sum(t["pnl"] for t in recent))
        assert b["trades_won"] == sum(t["pnl"] > 0 for t in recent)
        assert sorted(p["symbol"] for p in b["positions"]) == sorted(doc["engine"]["positions"])
        for p in b["positions"]:
            raw = doc["engine"]["positions"][p["symbol"]]
            assert p["unrealised"] == pytest.approx(raw["side"] * raw["qty"] * (raw["last_price"] - raw["entry_price"]))
            assert p["stop"] == raw["stop"]
        assert b["halted"] == doc["engine"]["halted"]
        assert b["paper"]["trades"] == len(ledger) and b["paper"]["days"] == pytest.approx(80 / 24, abs=0.05)
        assert b["paper"]["total_return"] == pytest.approx(b["pnl_total"] / 10000.0)
        assert b["decisions"]["entry"] >= 1
        bt = b["backtest"]
        assert bt["window"] == "wf_validation" and bt["total_return"] == -0.159 and bt["trades"] == 652
        assert bt["return_per_day"] == pytest.approx(-0.159 / (1.374 * 365.25))
    assert set(r["alerts"]) == {"feed_incomplete", "missed_bars"}
    assert r["alerts"]["feed_incomplete"] == {"level": "warn", "count": 1,
                                              "last_utc": (w.bar(K0 + 70) + HOUR + pd.Timedelta(minutes=7)).isoformat(),
                                              "last_message": r["alerts"]["feed_incomplete"]["last_message"]}
    assert r["alerts"]["missed_bars"]["count"] == 2
    assert r["promotion"]["challengers"]["challenger_1"]["ready"] is False
    json.dumps(r, allow_nan=False)                            # the whole report is strict JSON


def test_weekly_report_covers_the_whole_run_and_a_missing_results_file(traded):
    w = traded
    r = report.build_report(w.state, hours=168, now=w.now, results_dir=w.root / "no_results")
    b = r["books"]["champion"]
    assert b["pnl_period"] == pytest.approx(b["pnl_total"])   # the book is younger than a week
    assert len(b["trades"]) == len(read_jsonl(w.state / "ledger_champion.jsonl"))
    assert b["backtest"] is None


def test_render_is_plain_text_a_person_can_read(traded):
    w = traded
    text = report.render(report.build_report(w.state, hours=168, now=w.now, results_dir=w.results))
    for needle in ("PAPER", "HEALTHY", "champion", "challenger_1", "ref_donchian", "Closed trades", "Open positions",
                   "Alerts", "feed_incomplete", "Promotion", "backtest", "stop", "last 168 hours"):
        assert needle in text, needle
    assert "NOT HEALTHY" not in text and not re.search(r"\bnan\b|\bNone\b", text)
    ledger = read_jsonl(w.state / "ledger_champion.jsonl")
    assert ledger[-1]["symbol"] in text
    assert "challenger_2: no book" in text


def test_report_shows_a_halt_and_the_kill_switch(traded, tmp_path):
    w = traded
    state = tmp_path / "state"
    shutil.copytree(w.state, state)                           # leave the shared run untouched
    (state / "KILL").write_text("")
    now = w.bar(K0 + 80) + HOUR + pd.Timedelta(minutes=7)
    w.source.now = now
    paper.tick(w.config, state, now=now, source=w.source)
    r = report.build_report(state, now=now + pd.Timedelta(minutes=2), results_dir=w.results)
    assert r["health"]["killed"] is True and r["books"]["champion"]["halted"] is True
    assert r["books"]["champion"]["halt_reason"] == "manual kill" and "killed" in r["alerts"]
    text = report.render(r)
    assert "KILL SWITCH" in text and "manual kill" in text


def test_report_cli_prints_markdown_or_json_and_always_exits_zero(traded, capsys):
    w = traded
    assert report.main(["--state", str(w.state), "--results", str(w.results)]) == 0
    out = capsys.readouterr().out
    assert "champion" in out and "Promotion" in out
    assert report.main(["--state", str(w.state), "--hours", "168", "--json", "--results", str(w.results)]) == 0
    assert json.loads(capsys.readouterr().out)["hours"] == 168
    assert report.main(["--state", str(w.root / "empty")]) == 0           # nothing there yet: still a report
    assert "no heartbeat" in capsys.readouterr().out
