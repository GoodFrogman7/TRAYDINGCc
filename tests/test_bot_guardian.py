"""guardian.py: kill switch, feed pre-flight, universe cap, data checks, halts, alert log."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from desk.bot import config as C
from desk.bot import feed as F
from desk.bot import guardian as G
from desk.engine.core import Costs, Engine, Order, Position, Risk
from test_bot_fakes import ALTS, BTC, ETH, make_frames, no_network, read_jsonl  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")
MODEL = {"pooled_a": 0.0, "pooled_k": 0.04, "per_symbol": {}}


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "bot.yaml"
    p.write_text("mode: paper\n")
    return C.load_config(p)


def fetched(last="2026-07-10 13:00", syms=(BTC, ETH, ALTS[0]), server="2026-07-10 14:07:00", errors=None):
    frames = {s: df[df.index <= ts(last)] for s, df in make_frames(n=400).items() if s in syms}
    return F.Fetched(frames=frames, errors=dict(errors or {}), server_time=None if server is None else ts(server))


NOW, ASOF = ts("2026-07-10 14:07:00"), ts("2026-07-10 14:00")


def codes(v) -> list[str]:
    return [a.code for a in (v.alerts if isinstance(v, G.Verdict) else v)]


# ------------------------------------------------------------------- kill switch
def test_kill_requested_by_config_or_by_file(tmp_path, cfg):
    assert G.kill_requested(cfg, tmp_path) is False
    (tmp_path / "KILL").write_text("")
    assert G.kill_requested(cfg, tmp_path) is True
    (tmp_path / "KILL").unlink()
    p = tmp_path / "bot.yaml"
    p.write_text("mode: paper\nkill: true\n")
    assert G.kill_requested(C.load_config(p), tmp_path) is True


# -------------------------------------------------------------------- preflight
def test_preflight_healthy_feed(cfg):
    v = G.preflight(fetched(), [BTC, ETH, ALTS[0]], NOW, ASOF, cfg, None)
    assert v.usable and not v.frozen and v.alerts == []
    assert v.t_last == ts("2026-07-10 13:00") and v.age_minutes == pytest.approx(7.0)


def test_preflight_required_symbol_missing_is_not_usable(cfg):
    f = fetched(syms=(BTC, ETH), errors={ALTS[0]: "RuntimeError: outage"})
    v = G.preflight(f, [BTC, ETH, ALTS[0]], NOW, ASOF, cfg, ts("2026-07-10 12:00"))
    assert not v.usable and not v.frozen and v.t_last is None
    assert codes(v) == ["feed_incomplete"] and v.alerts[0].level == "warn"
    assert v.alerts[0].detail["failed"] == {ALTS[0]: "RuntimeError: outage"}
    assert v.age_minutes == pytest.approx(67.0)               # measured from the last good feed time
    assert v.unusable_since == NOW and v.t_feed is None       # the run of unusable ticks starts now
    # BTC itself missing, and no earlier feed time: aged from the bar an hourly bot would have had
    v = G.preflight(fetched(syms=(ETH,), errors={BTC: "x"}), [BTC, ETH], NOW, ASOF, cfg, None)
    assert not v.usable and codes(v) == ["feed_incomplete"] and not v.frozen
    assert v.age_minutes == pytest.approx(67.0) and v.unusable_since == NOW


def test_preflight_failed_context_symbol_is_only_a_warning(cfg):
    f = fetched(syms=(BTC, ETH), errors={ALTS[0]: "RuntimeError: outage"})
    v = G.preflight(f, [BTC, ETH], NOW, ASOF, cfg, None)
    assert v.usable and codes(v) == ["context_missing"] and v.alerts[0].level == "warn"


def test_preflight_clock_skew_and_missing_venue_clock(cfg):
    v = G.preflight(fetched(server="2026-07-10 14:07:31"), [BTC, ETH], NOW, ASOF, cfg, None)
    assert not v.usable and codes(v) == ["clock_skew"] and v.alerts[0].level == "critical"
    assert v.alerts[0].detail["skew_seconds"] == pytest.approx(-31.0)
    v = G.preflight(fetched(server="2026-07-10 14:07:30"), [BTC, ETH], NOW, ASOF, cfg, None)
    assert v.usable and v.alerts == []
    slow = fetched(server="2026-07-10 14:07:40")              # the answer took 40 s to arrive (retries):
    slow.server_time_delay = 40.0                             # our clock had moved on by then, so no skew
    assert G.preflight(slow, [BTC, ETH], NOW, ASOF, cfg, None).usable
    v = G.preflight(fetched(server=None), [BTC, ETH], NOW, ASOF, cfg, None)
    assert not v.usable and codes(v) == ["feed_incomplete"] and "clock" in v.alerts[0].message


def test_preflight_late_then_frozen(cfg):
    v = G.preflight(fetched(last="2026-07-10 12:00"), [BTC, ETH], NOW, ASOF, cfg, None)
    assert v.usable and not v.frozen and codes(v) == ["feed_late"] and v.alerts[0].level == "warn"
    assert v.t_last == ts("2026-07-10 12:00") and v.age_minutes == pytest.approx(67.0)
    v = G.preflight(fetched(last="2026-07-10 11:00"), [BTC, ETH], NOW, ASOF, cfg, None)
    assert v.usable and v.frozen and codes(v) == ["feed_late", "feed_frozen"]
    assert v.alerts[1].level == "critical" and v.age_minutes == pytest.approx(127.0)


def test_preflight_unusable_feed_freezes_on_what_the_bot_saw_while_awake(cfg):
    f = fetched(syms=(BTC, ETH), errors={ALTS[0]: "x"})
    req = [BTC, ETH, ALTS[0]]
    first_bad = ts("2026-07-10 13:07:00")                     # the previous tick, an hour ago, was unusable too
    # hourly ticks: good at 12:07 (bar 11:00), bad at 13:07, bad again now: 127 minutes without data
    v = G.preflight(f, req, NOW, ASOF, cfg, ts("2026-07-10 11:00"), first_bad)
    assert not v.usable and v.frozen and codes(v) == ["feed_incomplete", "feed_frozen"]
    assert v.age_minutes == pytest.approx(127.0) and v.unusable_since == first_bad and v.alerts[1].level == "critical"
    # the scheduler slept for hours and THIS is the first failed fetch: 67 minutes, not the age of the old bar
    v = G.preflight(f, req, NOW, ASOF, cfg, ts("2026-07-10 07:00"), None)
    assert not v.usable and not v.frozen and v.age_minutes == pytest.approx(67.0) and v.unusable_since == NOW
    # ... a second failed tick three minutes later is still not frozen, one an hour later is
    soon = fetched(syms=(BTC, ETH), errors={ALTS[0]: "x"}, server="2026-07-10 14:10:00")
    v = G.preflight(soon, req, NOW + pd.Timedelta(minutes=3), ASOF, cfg, ts("2026-07-10 07:00"), NOW)
    assert not v.frozen and v.age_minutes == pytest.approx(70.0)
    later = fetched(syms=(BTC, ETH), errors={ALTS[0]: "x"}, server="2026-07-10 15:07:00")
    v = G.preflight(later, req, NOW + pd.Timedelta(hours=1), ASOF + pd.Timedelta(hours=1), cfg,
                    ts("2026-07-10 07:00"), NOW)
    assert v.frozen and v.age_minutes == pytest.approx(127.0) and v.unusable_since == NOW
    # a feed that has NEVER been usable (first deployment) freezes the same way: there is no feed time to wait for
    v = G.preflight(f, req, NOW, ASOF, cfg, None, None)
    assert not v.usable and not v.frozen and v.unusable_since == NOW
    v = G.preflight(f, req, NOW, ASOF, cfg, None, first_bad)
    assert v.frozen and codes(v) == ["feed_incomplete", "feed_frozen"]
    # a second tick inside the same hour as the last good one: the data is only minutes old
    v = G.preflight(f, req, NOW, ASOF, cfg, ts("2026-07-10 13:00"), None)
    assert not v.frozen and v.age_minutes == pytest.approx(7.0)
    # an `unusable_since` from the future (the clock was set back) is not believed
    v = G.preflight(f, req, NOW, ASOF, cfg, None, NOW + pd.Timedelta(days=3))
    assert v.unusable_since == NOW and not v.frozen


def test_preflight_never_freezes_on_a_clock_that_disagrees_with_the_venue(cfg):
    ahead = NOW + pd.Timedelta(hours=3)                       # this machine's clock is three hours fast
    f = fetched(server="2026-07-10 14:07:00")
    v = G.preflight(f, [BTC, ETH], ahead, ASOF + pd.Timedelta(hours=3), cfg, ts("2026-07-10 13:00"), NOW)
    assert not v.usable and not v.frozen and codes(v) == ["clock_skew"] and v.clock == "skew"
    assert v.age_minutes is None and v.unusable_since == NOW  # nothing is concluded from the wrong clock
    assert G.check_clock(None, 0.0, NOW, cfg)[0] == "unknown"
    assert G.check_clock(ts("2026-07-10 14:07:10"), 0.0, NOW, cfg) == ("ok", [])
    # an unreadable venue clock is an unusable feed like any other and does freeze if it lasts
    v = G.preflight(fetched(server=None), [BTC, ETH], NOW, ASOF, cfg, ts("2026-07-10 11:00"), ts("2026-07-10 13:07"))
    assert not v.usable and v.frozen and v.clock == "unknown" and codes(v) == ["feed_incomplete", "feed_frozen"]


def test_preflight_waits_one_tick_for_a_held_symbols_newest_bar(cfg):
    f = fetched()
    f.frames[ALTS[0]] = f.frames[ALTS[0]].iloc[:-1]            # its 13:00 candle is not served yet
    req = [BTC, ETH, ALTS[0]]
    v = G.preflight(f, req, NOW, ASOF, cfg, None)             # nobody holds it: the bar is simply missing
    assert v.usable and v.t_last == ts("2026-07-10 13:00") and v.alerts == []
    v = G.preflight(f, req, NOW, ASOF, cfg, None, None, {ALTS[0]})
    assert v.usable and not v.frozen and v.t_last == ts("2026-07-10 12:00") and v.t_feed == ts("2026-07-10 13:00")
    assert codes(v) == ["feed_late"] and v.alerts[0].symbol == ALTS[0] and v.alerts[0].level == "warn"
    assert v.age_minutes == pytest.approx(7.0)                # the feed itself is fresh: waiting is not freezing
    f.frames[ALTS[0]] = f.frames[ALTS[0]].iloc[:-1]            # two bars behind: accepted as missing bars
    v = G.preflight(f, req, NOW, ASOF, cfg, None, None, {ALTS[0]})
    assert v.usable and v.t_last == ts("2026-07-10 13:00") and v.alerts == []


def test_kill_file_is_found_under_the_names_an_editor_may_give_it(tmp_path, cfg):
    for name in ("KILL", "kill", "Kill.txt", "KILL.md"):
        (tmp_path / name).write_text("")
        assert G.kill_requested(cfg, tmp_path) is True and G.kill_file(tmp_path).name == name
        (tmp_path / name).unlink()
    for name in ("killer.txt", "skill", "KILLED"):
        (tmp_path / name).write_text("")
    (tmp_path / "kill.d").mkdir()                             # a folder is not the switch
    assert G.kill_requested(cfg, tmp_path) is False and G.kill_file(tmp_path / "absent") is None


def test_preflight_ignores_trailing_missing_bars_when_finding_the_newest_real_bar(cfg):
    f = fetched()
    btc = f.frames[BTC].copy()
    btc.loc[btc.index[-2:], "bar_missing"] = True
    f.frames[BTC] = btc
    v = G.preflight(f, [BTC, ETH], NOW, ASOF, cfg, None)
    assert v.t_last == ts("2026-07-10 11:00") and v.frozen


# ----------------------------------------------------------------- universe_cap
def test_universe_cap():
    uni = {"2026-09": ["A"], "2026-10": ["A"]}
    assert G.universe_cap(ts("2026-10-15 07:00"), uni) == ts("2026-10-15 07:00")
    assert G.universe_cap(ts("2026-11-01 00:00"), uni) == ts("2026-10-31 23:00")
    assert G.universe_cap(ts("2027-01-03 05:00"), uni) == ts("2026-10-31 23:00")
    assert G.universe_cap(ts("2026-08-31 23:00"), uni) is None
    assert G.universe_cap(ts("2026-10-31 23:00"), {}) is None
    assert G.universe_cap(ts("2026-12-31 23:00"), {"2026-12": []}) == ts("2026-12-31 23:00")


# ------------------------------------------------------------------- check_data
def test_check_data_reports_gaps_delistings_bad_bars_and_lost_inputs(cfg):
    raw = {s: df for s, df in make_frames(n=300).items()}
    t_last = raw[BTC].index[-1]
    raw[ETH] = raw[ETH].iloc[:-4]                             # 4 hours without a candle
    raw[ALTS[0]] = raw[ALTS[0]].iloc[:-100]                   # gone for good
    raw[ALTS[1]] = raw[ALTS[1]].copy()
    raw[ALTS[1]].loc[raw[ALTS[1]].index[50], "high"] = -1.0   # a bad bar
    raw[BTC] = raw[BTC].copy()
    raw[BTC].loc[t_last, ["oi", "ls_ratio"]] = np.nan         # two inputs vanish on the newest bar
    raw[ALTS[2]] = raw[ALTS[2]].copy()
    raw[ALTS[2]].loc[raw[ALTS[2]].index[-2:], "oi"] = np.nan  # already gone an hour ago: reported back then
    data, gaps, bad = F.prepare(raw, t_last, cfg.delist_after_bars, MODEL)
    watched = {BTC, ETH, ALTS[0], ALTS[1], ALTS[2]}
    needs = {"champion": ("oi", "ls_ratio"), "challenger_1": (), "challenger_2": ("liq_vol",)}
    alerts = G.check_data(data, gaps, bad, watched, needs, t_last, cfg)
    by = {(a.code, a.symbol, a.book): a for a in alerts}
    assert set(by) == {("bar_missing", ETH, ""), ("symbol_delisted", ALTS[0], ""), ("bad_bar", ALTS[1], ""),
                       ("inputs_missing", BTC, "champion")}
    assert all(a.level == "warn" for a in alerts)
    assert by[("bar_missing", ETH, "")].detail == {"hours": 4}
    assert by[("symbol_delisted", ALTS[0], "")].detail["hours"] == 100
    assert by[("bad_bar", ALTS[1], "")].detail == {"bars": 1}
    assert by[("inputs_missing", BTC, "champion")].detail == {"columns": ["oi", "ls_ratio"]}
    # symbols nobody holds and that are outside this month's universe are not reported
    assert G.check_data(data, gaps, bad, {ALTS[2]}, needs, t_last, cfg) == []


# ------------------------------------------------------------------------- halt
def engine_with_book() -> Engine:
    eng = Engine(Costs(), Risk(), log_events=True)
    st = eng.state
    st.last_time = "2026-07-10T12:00:00+00:00"
    st.orders["PF_AAAUSD"] = Order("PF_AAAUSD", 1, float("nan"), 90.0, float("nan"), 1, st.last_time)
    st.positions[BTC] = Position(BTC, 1, 0.1, 100.0, st.last_time, 95.0, 95.0, float("nan"), 0.5, False, False,
                                 last_price=100.0)
    return eng


def test_halt_cancels_orders_flags_exits_and_blocks_until_the_next_utc_day():
    eng = engine_with_book()
    now = ts("2026-07-10 14:07")
    G.halt(eng, "frozen data feed", now)
    st = eng.state
    assert st.halted and st.halt_reason == "frozen data feed" and st.halt_day == int(now.timestamp() // 86400)
    assert not st.orders and st.positions[BTC].exit_pending == "guardian"
    assert [e["event"] for e in eng.events] == ["order_cancelled", "guardian_halt"]
    assert eng.events[-1]["time"] == "2026-07-10T12:00:00+00:00" and eng.events[-1]["reason"] == "frozen data feed"
    # already halted: nothing is logged again, only the day is pushed out
    G.halt(eng, "manual kill", ts("2026-07-11 00:07"))
    assert st.halt_reason == "frozen data feed" and st.halt_day == int(now.timestamp() // 86400) + 1
    assert len(eng.events) == 2
    G.halt(eng, "manual kill", ts("2026-07-10 23:07"))        # never moves backwards
    assert st.halt_day == int(now.timestamp() // 86400) + 1


def test_halt_on_a_book_that_has_no_bar_yet_is_stamped_with_the_clock():
    eng = Engine(Costs(), Risk(), log_events=True)
    G.halt(eng, "manual kill", ts("2026-07-10 14:07"))
    assert eng.state.halted and eng.events[0]["time"] == "2026-07-10T14:07:00+00:00"


# ----------------------------------------------------------------- write_alerts
def test_write_alerts_appends_one_strict_json_line_each(tmp_path):
    a = [G.Alert("warn", "feed_late", "the feed is one bar late"),
         G.Alert("critical", "book_error", "boom", book="champion", symbol=BTC,
                 detail={"x": float("nan"), "n": np.int64(3), "t": ts("2026-07-10 14:00")})]
    G.write_alerts(tmp_path, a, "2026-07-10T14:07:00+00:00")
    G.write_alerts(tmp_path, a[:1], "2026-07-10T15:07:00+00:00")
    G.write_alerts(tmp_path, [], "2026-07-10T16:07:00+00:00")
    rows = read_jsonl(tmp_path / "alerts.jsonl")
    assert len(rows) == 3
    assert rows[0] == {"tick_utc": "2026-07-10T14:07:00+00:00", "level": "warn", "code": "feed_late", "book": "",
                       "symbol": "", "message": "the feed is one bar late", "detail": None}
    assert rows[1]["detail"] == {"x": None, "n": 3, "t": "2026-07-10T14:00:00+00:00"}
    assert "NaN" not in (tmp_path / "alerts.jsonl").read_text()
    assert list(json.loads((tmp_path / "alerts.jsonl").read_text().splitlines()[0])) == \
        ["tick_utc", "level", "code", "book", "symbol", "message", "detail"]
