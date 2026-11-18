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
    frozen: bool                      # the feed is older than stale_feed_minutes: halt every book
    t_last: pd.Timestamp | None       # BTC's newest real bar (None while not usable)
    age_minutes: float | None
    alerts: list[Alert] = field(default_factory=list)


def kill_requested(cfg: BotConfig, state_dir: Path) -> bool:
    """The manual kill switch: `kill: true` in the config, or a file named KILL in the state directory."""
    return bool(cfg.kill) or (Path(state_dir) / "KILL").exists()


def _newest_real_bar(df: pd.DataFrame) -> pd.Timestamp | None:
    if "bar_missing" in df:
        df = df[~df["bar_missing"].fillna(True).astype(bool)]
    return None if df.empty else utc(df.index[-1])


def preflight(fetched: Fetched, required: list[str], now: pd.Timestamp, asof: pd.Timestamp, cfg: BotConfig,
              prev_feed_time: pd.Timestamp | None) -> Verdict:
    """Decide whether this tick may process bars, and whether the feed is frozen."""
    now, asof = utc(now), utc(asof)
    alerts: list[Alert] = []
    usable = True
    failed = {s: fetched.errors.get(s, "no data") for s in required if s not in fetched.frames}
    t_last = _newest_real_bar(fetched.frames[BTC]) if BTC in fetched.frames else None
    if t_last is None and BTC not in failed:
        failed[BTC] = fetched.errors.get(BTC, "no real bar")
    if failed:
        usable = False
        alerts.append(Alert("warn", "feed_incomplete",
                            f"could not fetch {', '.join(sorted(failed))}: no book advances; the missed bars are "
                            f"replayed on the next good tick", detail={"failed": failed}))
    context = {s: e for s, e in fetched.errors.items() if s not in required}
    if context:
        alerts.append(Alert("warn", "context_missing",
                            f"left out {', '.join(sorted(context))} (not required this month): fetch failed",
                            detail={"failed": context}))
    if fetched.server_time is None:
        usable = False
        if not failed:
            alerts.append(Alert("warn", "feed_incomplete",
                                "could not read the venue clock, so this machine's clock cannot be checked: "
                                "no book advances", detail={"failed": {"venue clock": "no serverTime"}}))
    else:
        # our clock when the venue answered = the tick's clock + the time the answer took
        skew = (now - utc(fetched.server_time)).total_seconds() + fetched.server_time_delay
        if abs(skew) > cfg.max_clock_skew_seconds:
            usable = False
            alerts.append(Alert("critical", "clock_skew",
                                f"this machine's clock differs from the venue's by {skew:+.0f} s "
                                f"(limit {cfg.max_clock_skew_seconds} s): nothing is processed",
                                detail={"skew_seconds": skew}))
    if usable and t_last < asof - HOUR:
        behind = int(round((asof - HOUR - t_last) / HOUR))
        alerts.append(Alert("warn", "feed_late", f"the newest BTC bar is {t_last.isoformat()}, {behind} bar(s) behind: "
                                                 f"waiting", detail={"bars_behind": behind}))
    since = t_last if usable else prev_feed_time
    age = None if since is None else (now - (utc(since) + HOUR)).total_seconds() / 60.0
    frozen = age is not None and age > cfg.stale_feed_minutes
    if frozen:
        alerts.append(Alert("critical", "feed_frozen",
                            f"no fresh market data for {age:.0f} minutes (limit {cfg.stale_feed_minutes}): every book "
                            f"is halted, orders cancelled, positions closed at the next bar",
                            detail={"age_minutes": age}))
    return Verdict(usable=usable, frozen=frozen, t_last=t_last if usable else None, age_minutes=age, alerts=alerts)


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
            alerts.append(Alert("warn", "bad_bar", f"{s}: {bad[s]} bar(s) with impossible prices in the window were "
                                                   f"treated as missing", symbol=s, detail={"bars": bad[s]}))
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
    with open(path, "ab") as f:
        f.write(("\n".join(lines) + "\n").encode())
        f.flush()
        os.fsync(f.fileno())
