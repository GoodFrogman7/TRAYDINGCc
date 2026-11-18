"""The Guardian's bot-level duties: kill switch, feed pre-flight, data checks, halts, alert log.

The per-order limits (stop attached, stop distance, position and gross caps,
universe, daily loss, losing streak) live inside `desk.engine.core.Engine`,
so the paper bot and the backtests enforce exactly the same ones.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..engine.core import Engine
from .config import BotConfig
from .feed import BTC, HOUR, Fetched, utc

LEVELS = ("info", "warn", "critical")
LATE_GRACE_BARS = 1        # ticks a held symbol's newest bar may lag BTC's before it counts as missing
CONFIRM_AFTER_MINUTES = 20   # an unusable feed is frozen only if a run at least this much earlier was unusable too


@dataclass
class Alert:
    level: str               # info | warn | critical
    code: str
    message: str
    book: str = ""
    symbol: str = ""
    detail: dict | None = None


@dataclass
class Verdict:
    usable: bool                      # the bars may be processed this tick
    frozen: bool                      # no usable data for longer than stale_feed_minutes: halt every book
    t_last: pd.Timestamp | None       # the newest bar the books may process (None while not usable)
    age_minutes: float | None
    alerts: list[Alert] = field(default_factory=list)
    t_feed: pd.Timestamp | None = None        # BTC's newest real bar (>= t_last; None while not usable)
    unusable_since: pd.Timestamp | None = None   # clock time of the first tick of this run of unusable ticks
    clock: str = "ok"                 # ok | skew | unknown


def kill_file(state_dir: Path) -> Path | None:
    """The kill-switch file in the state directory: KILL, in any letter case, with or without an
    extension (an editor may save it as KILL.txt)."""
    try:
        for p in sorted(Path(state_dir).iterdir()):
            if p.name.lower().split(".", 1)[0] == "kill" and p.is_file():
                return p
    except OSError:
        pass
    return None


def kill_requested(cfg: BotConfig, state_dir: Path) -> bool:
    """The manual kill switch: `kill: true` in the config, or a file named KILL in the state directory."""
    return bool(cfg.kill) or kill_file(state_dir) is not None


def _newest_real_bar(df: pd.DataFrame) -> pd.Timestamp | None:
    if "bar_missing" in df:
        df = df[~df["bar_missing"].fillna(True).astype(bool)]
    return None if df.empty else utc(df.index[-1])


def check_clock(server_time: pd.Timestamp | None, delay: float, now: pd.Timestamp, cfg: BotConfig
                ) -> tuple[str, list[Alert]]:
    """Compare this machine's clock with the venue's BEFORE anything is decided on it:
    ("ok" | "skew" | "unknown", alerts). Nothing is processed, retired or halted on a clock that is not ok."""
    if server_time is None:
        return "unknown", [Alert("warn", "feed_incomplete",
                                 "could not read the venue clock, so this machine's clock cannot be checked: "
                                 "no book advances", detail={"failed": {"venue clock": "no serverTime"}})]
    # our clock when the venue answered = the tick's clock + the time the answer took
    skew = (utc(now) - utc(server_time)).total_seconds() + delay
    if abs(skew) > cfg.max_clock_skew_seconds:
        return "skew", [Alert("critical", "clock_skew",
                              f"this machine's clock differs from the venue's by {skew:+.0f} s "
                              f"(limit {cfg.max_clock_skew_seconds} s): nothing is processed and no book is "
                              f"touched until the clock is right", detail={"skew_seconds": skew})]
    return "ok", []


def preflight(fetched: Fetched, required: list[str], now: pd.Timestamp, asof: pd.Timestamp, cfg: BotConfig,
              prev_feed_time: pd.Timestamp | None, unusable_since: pd.Timestamp | None = None,
              held: set[str] | frozenset = frozenset()) -> Verdict:
    """Decide whether this tick may process bars, up to which bar, and whether the feed is frozen.

    `prev_feed_time` is the feed time of the last usable tick and `unusable_since` the clock time of the
    first tick of the current run of unusable ticks (both from the previous heartbeat; None = unknown or
    the previous tick was usable). `held` = symbols with a position or an order in any book.

    Frozen means more than `stale_feed_minutes` without data, counted only over time the bot was awake:
      * usable feed: minutes from the close of BTC's newest real bar to now;
      * unusable feed: minutes from the newest data the bot could have had if it had been ticking every
        hour, i.e. the later of (close of the last usable feed bar) and (close of the bar before the one
        the first unusable tick should have processed). The first tick of a run of unusable ticks is never
        frozen, whatever that age (a run that starts at hh:42 is 102 minutes from that close, and one
        failed download proves nothing): a tick at least CONFIRM_AFTER_MINUTES later that is unusable too
        confirms it;
      * a clock that disagrees with the venue's: never frozen (this machine's time cannot be trusted)."""
    now, asof = utc(now), utc(asof)
    clock, alerts = check_clock(fetched.server_time, fetched.server_time_delay, now, cfg)
    usable = clock == "ok"
    t_feed = t_last = None
    if clock == "ok":                         # with a doubtful clock no bars were asked for
        failed = {s: fetched.errors.get(s, "no data") for s in required if s not in fetched.frames}
        t_feed = _newest_real_bar(fetched.frames[BTC]) if BTC in fetched.frames else None
        if t_feed is None and BTC not in failed:
            failed[BTC] = fetched.errors.get(BTC, "no real bar")
        if failed:
            usable = False
            alerts.append(Alert("warn", "feed_incomplete",
                                f"could not fetch {', '.join(sorted(failed))}: no book advances; the missed bars "
                                f"are replayed on the next good tick", detail={"failed": failed}))
        context = {s: e for s, e in fetched.errors.items() if s not in required}
        if context:
            alerts.append(Alert("warn", "context_missing",
                                f"left out {', '.join(sorted(context))} (not required this month): fetch failed",
                                detail={"failed": context}))
    if usable:
        t_last = t_feed
        if t_feed < asof - HOUR:
            behind = int(round((asof - HOUR - t_feed) / HOUR))
            alerts.append(Alert("warn", "feed_late", f"the newest BTC bar is {t_feed.isoformat()}, {behind} bar(s) "
                                                     f"behind: waiting", detail={"bars_behind": behind}))
        # a held symbol whose newest candle is not served yet: wait for it instead of inventing an empty
        # bar that would never be redone (its stop would not be checked against the real bar)
        for s in sorted(held):
            newest = _newest_real_bar(fetched.frames[s]) if s in fetched.frames else None
            if newest is None or not newest < t_feed or t_feed - newest > LATE_GRACE_BARS * HOUR:
                continue
            t_last = min(t_last, newest)
            alerts.append(Alert("warn", "feed_late",
                                f"{s} is held and its bar {(newest + HOUR).isoformat()} is not published yet (BTC's "
                                f"is): waiting one tick before treating that bar as missing", symbol=s,
                                detail={"newest_bar": newest.isoformat(), "btc_newest_bar": t_feed.isoformat()}))
        since, unusable_since, confirmed = t_feed + HOUR, None, True
    elif clock == "skew":
        return Verdict(False, False, None, None, alerts, clock=clock, unusable_since=unusable_since)
    else:
        if unusable_since is None or not utc(unusable_since) <= now:
            unusable_since = now
        unusable_since = utc(unusable_since)
        # one failed download proves nothing about the feed, and neither does a second run minutes later
        # (GitHub starts delayed runs back to back): the freeze needs an earlier unusable run to confirm it
        confirmed = now - unusable_since >= pd.Timedelta(minutes=CONFIRM_AFTER_MINUTES)
        # the close of the bar before the newest one that was closed at the first unusable tick
        since = (unusable_since - pd.Timedelta(seconds=cfg.settle_seconds)).floor("h") - HOUR
        if prev_feed_time is not None:
            since = max(since, utc(prev_feed_time) + HOUR)
    age = (now - since).total_seconds() / 60.0
    frozen = age > cfg.stale_feed_minutes and confirmed
    if frozen:
        alerts.append(Alert("critical", "feed_frozen",
                            f"no usable market data for {age:.0f} minutes (limit {cfg.stale_feed_minutes}): every book "
                            f"is halted, orders cancelled, positions closed at the next bar",
                            detail={"age_minutes": age}))
    return Verdict(usable=usable, frozen=frozen, t_last=t_last, age_minutes=age, alerts=alerts,
                   t_feed=t_feed if usable else None,
                   unusable_since=unusable_since, clock=clock)


def universe_cap(t_last: pd.Timestamp, universe: dict[str, list[str]]) -> pd.Timestamp | None:
    """The newest bar <= t_last whose month is in the universe file (None if there is none)."""
    t_last = utc(t_last)
    month = t_last.strftime("%Y-%m")
    known = [m for m in universe if m <= month]
    if not known:
        return None
    newest = max(known)
    if newest == month:
        return t_last
    y, m = int(newest[:4]), int(newest[5:7])
    next_month = pd.Timestamp(year=y + (m == 12), month=1 if m == 12 else m + 1, day=1, tz="UTC")
    return next_month - HOUR


def check_data(data: dict, gaps: dict, bad: dict, watched: set[str], needs: dict[str, tuple],
               t_last: pd.Timestamp, cfg: BotConfig) -> list[Alert]:
    """Warnings about the symbols that matter now (held, or in this month's universe)."""
    t_last = utc(t_last)
    alerts: list[Alert] = []
    for s in sorted(watched):
        g = gaps.get(s, 0)
        if g >= cfg.delist_after_bars:
            alerts.append(Alert("warn", "symbol_delisted",
                                f"{s} has printed no bar for {g} hours: treated as delisted (positions closed, "
                                f"orders cancelled)", symbol=s, detail={"hours": g}))
        elif g > 0:
            alerts.append(Alert("warn", "bar_missing",
                                f"{s} has printed no bar for {g} hour(s): positions kept at the last price, "
                                f"no new entries", symbol=s, detail={"hours": g}))
        if bad.get(s):
            alerts.append(Alert("warn", "bad_bar", f"{s}: {bad[s]} bar(s) with impossible or off-market prices in "
                                                   f"the window were treated as missing", symbol=s,
                                detail={"bars": bad[s]}))
    for book, cols in needs.items():
        for s in sorted(watched):
            df = data.get(s)
            if df is None or len(df) < 2 or utc(df.index[-1]) != t_last or bool(df["bar_missing"].iloc[-1]):
                continue
            lost = [c for c in cols if c in df and pd.isna(df[c].iloc[-1]) and pd.notna(df[c].iloc[-2])]
            if lost:
                alerts.append(Alert("warn", "inputs_missing",
                                    f"{s}: {', '.join(lost)} had a value an hour ago and has none on the newest bar; "
                                    f"the strategy cannot signal on it", book=book, symbol=s,
                                    detail={"columns": lost}))
    return alerts


def halt(engine: Engine, reason: str, now: pd.Timestamp) -> None:
    """Halt a book: cancel its orders, close its positions at the next bar's open, block entries.
    The engine has no public halt, so this calls its internal one. If the book is already halted only
    the halt day is pushed forward, so entries stay blocked until the UTC day after the last call."""
    now = utc(now)
    day = int(now.timestamp() // 86400)
    st = engine.state
    if st.halted:
        if day > st.halt_day:
            st.halt_day = day
        return
    engine._halt(reason, st.last_time or now.isoformat(), day)


def to_jsonable(o):
    """Plain JSON values: numpy scalars and timestamps converted, NaN and infinity as null."""
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [to_jsonable(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):      # numpy scalar
        o = o.item()
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def write_alerts(state_dir: Path, alerts: list[Alert], tick_utc: str) -> None:
    """Append this tick's alerts to alerts.jsonl (one JSON object per line)."""
    if not alerts:
        return
    lines = [json.dumps(to_jsonable({"tick_utc": tick_utc, "level": a.level, "code": a.code, "book": a.book,
                                     "symbol": a.symbol, "message": a.message, "detail": a.detail}), allow_nan=False)
             for a in alerts]
    path = Path(state_dir) / "alerts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab+") as f:
        size = f.seek(0, os.SEEK_END)
        if size:                              # a line torn by a crash must not swallow the next alert
            f.seek(size - 1)
            if f.read(1) != b"\n":
                lines.insert(0, "")
        f.write(("\n".join(lines) + "\n").encode())
        f.flush()
        os.fsync(f.fileno())
