"""The paper-trading bot: one hourly tick, a loop for an always-on machine, status, and the files it keeps.

PAPER ONLY. A tick fetches closed hourly bars from the venue's public market
data, feeds each new bar to the same `desk.engine.core.Engine` the backtests
use, and writes what happened under the state directory. No order ever leaves
this process.

    python -m desk.bot.paper tick   [--config config/bot.yaml] [--state state]
    python -m desk.bot.paper status [--state state] [--json]
    python -m desk.bot.paper loop   [--config ...] [--state ...]

Each book (champion, challenger_1, challenger_2) is one transaction per tick:
its log lines are appended first, then its state file is replaced atomically.
The state file records the committed size of each log, so lines left behind by
a crashed tick are cut off before the bar is redone.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..data import store
from ..engine.core import Costs, Engine, FeedBase, State, attach
from . import feed, guardian
from .config import BOOK_NAMES, BookConfig, BotConfig, ConfigError, fingerprint, load_config, load_strategy
from .guardian import Alert, to_jsonable

CONFIG = "config/bot.yaml"
STATE = "state"
SCHEMA = 1
MAX_LOG_MB = 5                    # decisions_* and alerts rotate above this size
LOCK_STALE_MINUTES = 20
STALE_HEARTBEAT_MINUTES = 120     # `status` calls the bot unhealthy after this long without a tick
HOUR = pd.Timedelta(hours=1)
LOCK, HEARTBEAT = "tick.lock", "heartbeat.json"
LOG_FILES = {"decisions": "decisions_{book}.jsonl", "ledger": "ledger_{book}.jsonl", "equity": "equity_{book}.csv"}
EQUITY_HEADER = "time,equity,gross,tick_utc"
MANUAL_KILL, FROZEN_FEED = "manual kill", "frozen data feed"

# the reason written for a decision when the engine does not give one
REASONS = {
    "book_started": "new book: starts flat on this bar and never trades bars from before it existed",
    "resume": "kill switch released: the manual halt is cleared",
    "order_created": "strategy signal at the close of this bar; the order can fill from the next bar",
    "order_expired": "the limit price was not reached while the order was valid",
    "order_cancelled": "order cancelled",
    "order_rejected": "order rejected by the Guardian",
    "signal_blocked": "signal blocked by the Guardian",
    "entry": "order filled",
    "exit": "position closed",
    "target_dropped": "take-profit dropped",
    "guardian_halt": "Guardian halt",
}


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


# ------------------------------------------------------------------ file storage
def atomic_write_json(path: Path, obj: dict) -> None:
    """Write strict JSON (NaN as null) to a temp file, fsync it, then replace `path` in one step."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(to_jsonable(obj), allow_nan=False, indent=1)
    with open(tmp, "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_lines(path: Path, lines: list[str]) -> int:
    """Append the lines with one write and fsync; returns the file's new size in bytes."""
    with open(path, "ab") as f:
        f.write("".join(line + "\n" for line in lines).encode())
        f.flush()
        os.fsync(f.fileno())
        return os.fstat(f.fileno()).st_size


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _log_path(state_dir: Path, kind: str, book: str) -> Path:
    return Path(state_dir) / LOG_FILES[kind].format(book=book)


def committed_bytes(state_dir: Path, book: str) -> dict | None:
    """The log sizes the book's state file vouches for (None if there is no readable state file)."""
    doc = _read_json(Path(state_dir) / f"{book}.json")
    try:
        return {k: int(doc["log_bytes"][k]) for k in LOG_FILES}
    except (TypeError, KeyError, ValueError):
        return None


def read_committed(state_dir: Path, kind: str, book: str) -> bytes:
    """The committed part of one of a book's live logs (bytes a crashed tick left behind are ignored)."""
    path = _log_path(state_dir, kind, book)
    if not path.exists():
        return b""
    data = path.read_bytes()
    sizes = committed_bytes(state_dir, book)
    return data if sizes is None else data[:sizes[kind]]


def read_log(state_dir: Path, stem: str, since: pd.Timestamp | None = None) -> list[dict]:
    """All rows of a .jsonl log, rotated files first: `decisions_champion`, `ledger_champion`, `alerts`.
    `since` keeps rows whose time (exit_time for trades, bar time for decisions, tick time for alerts)
    is at or after it."""
    state_dir = Path(state_dir)
    chunks = [p.read_bytes() for p in sorted((state_dir / "archive" / "rotated").glob(f"{stem}.*.jsonl"))]
    kind, _, book = stem.partition("_")
    if kind in LOG_FILES and book in BOOK_NAMES:
        chunks.append(read_committed(state_dir, kind, book))
    elif (state_dir / f"{stem}.jsonl").exists():
        chunks.append((state_dir / f"{stem}.jsonl").read_bytes())
    since = None if since is None else feed.utc(since)
    rows = []
    for chunk in chunks:
        for line in chunk.decode(errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue                      # a torn line from a crash
            if not isinstance(row, dict):
                continue
            if since is not None:
                when = row.get("exit_time") or row.get("time") or row.get("tick_utc")
                try:
                    if feed.utc(when) < since:
                        continue
                except (TypeError, ValueError):
                    continue
            rows.append(row)
    return rows


def _stamp(tick_utc: str) -> str:
    return feed.utc(tick_utc).strftime("%Y%m%dT%H%M%SZ")


def _free_path(path: Path) -> Path:
    """`path`, or `path` with -2, -3 ... before the suffix if it is taken."""
    n, out = 1, path
    while out.exists():
        n += 1
        out = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return out


def retire_book(state_dir: Path, book: str, why: str, tick_utc: str) -> Path:
    """Move a book's files to archive/<book>.<stamp>.<why>/: the logs first, the state file last, so a
    crash in between leaves a state file whose (missing) logs are simply accepted as shorter."""
    state_dir = Path(state_dir)
    dest = state_dir / "archive" / f"{book}.{_stamp(tick_utc)}.{why}"
    n = 1
    while dest.exists():
        n += 1
        dest = state_dir / "archive" / f"{book}.{_stamp(tick_utc)}.{why}-{n}"
    dest.mkdir(parents=True)
    moves = [_log_path(state_dir, kind, book) for kind in LOG_FILES]
    moves += sorted((state_dir / "archive" / "rotated").glob(f"decisions_{book}.*.jsonl"))
    moves.append(state_dir / f"{book}.json")
    for src in moves:
        if src.exists():
            os.replace(src, dest / src.name)
    return dest


def _rotate(state_dir: Path, stem: str, tick_utc: str) -> bool:
    path = Path(state_dir) / f"{stem}.jsonl"
    if not path.exists() or path.stat().st_size <= MAX_LOG_MB * 1024 * 1024:
        return False
    rotated = Path(state_dir) / "archive" / "rotated"
    rotated.mkdir(parents=True, exist_ok=True)
    os.replace(path, _free_path(rotated / f"{stem}.{_stamp(tick_utc)}.jsonl"))
    return True


def _take_lock(state_dir: Path, tick_utc: str) -> tuple[bool, bool]:
    """(got the lock, broke a stale one). The lock's age is its file time on the real clock."""
    path = Path(state_dir) / LOCK
    broke = False
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < LOCK_STALE_MINUTES * 60:
                return False, broke
            path.unlink(missing_ok=True)
            broke = True
            continue
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"pid": os.getpid(), "started_utc": _now().isoformat(timespec="seconds"),
                                "tick_utc": tick_utc}))
        return True, broke
    return False, broke


# ------------------------------------------------------------------------- books
def _zero_sizes() -> dict:
    return {k: 0 for k in LOG_FILES}


@dataclass
class _Book:
    name: str
    cfg: BookConfig | None                 # what the config asks for (None = no strategy)
    state: State | None = None             # None = no book on disk
    fp: dict | None = None                 # the fingerprint the book was started with
    started_bar: str | None = None
    log_bytes: dict = field(default_factory=_zero_sizes)
    closing: bool = False                  # the config no longer matches: flatten, retire

    def reset(self) -> None:
        self.state, self.fp, self.started_bar, self.closing = None, None, None, False
        self.log_bytes = _zero_sizes()


@dataclass
class _Market:
    data: dict
    base: FeedBase | None
    t_last: pd.Timestamp
    t_cap: pd.Timestamp | None
    i1: int                                # index after t_cap in base.index


@dataclass
class _Tick:
    state_dir: Path
    now: pd.Timestamp
    tick_utc: str
    alerts: list = field(default_factory=list)
    books: dict = field(default_factory=dict)          # heartbeat summaries
    feed: dict = field(default_factory=lambda: {"usable": False, "frozen": False, "feed_time": None,
                                                "age_minutes": None, "symbols": 0, "failed": []})
    killed: bool = False
    error: str | None = None
    t_end: pd.Timestamp | None = None

    def alert(self, level: str, code: str, message: str, book: str = "", symbol: str = "",
              detail: dict | None = None) -> None:
        self.alerts.append(Alert(level, code, message, book, symbol, detail))


def _parse_state(path: Path, name: str) -> tuple[State, dict, str, dict]:
    """Read a book's state file. Raises on anything that is not a schema-1 state of this book."""
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"not a schema {SCHEMA} state file")
    if doc.get("book") != name:
        raise ValueError(f"the file belongs to book {doc.get('book')!r}")
    st = State.from_json(doc["engine"])
    for v in (st.cash, st.equity, st.day_start_equity):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("the engine state holds a value that is not a number")
    if not isinstance(st.last_time, str):
        raise ValueError("last_time is not a string")
    fp = doc["strategy"]
    absent = [k for k in ("module", "name", "params", "valid_bars", "max_hold", "equity0") if k not in fp]
    if absent or not isinstance(fp["params"], dict):
        raise ValueError(f"the strategy fingerprint is incomplete: {absent or 'params'}")
    fp["valid_bars"], fp["max_hold"], fp["equity0"] = int(fp["valid_bars"]), int(fp["max_hold"]), float(fp["equity0"])
    sizes = {k: int(doc["log_bytes"][k]) for k in LOG_FILES}
    return st, fp, str(doc["started_bar"]), sizes


def _write_state(t: _Tick, b: _Book) -> None:
    atomic_write_json(t.state_dir / f"{b.name}.json", {
        "schema": SCHEMA, "book": b.name, "started_bar": b.started_bar, "updated_utc": t.tick_utc,
        "engine": b.state.to_json(), "strategy": b.fp, "log_bytes": b.log_bytes})


def _truncate(path: Path, size: int) -> None:
    with open(path, "r+b") as f:
        f.truncate(size)
        f.flush()
        os.fsync(f.fileno())


def _load_book(t: _Tick, cfg: BotConfig, name: str) -> _Book:
    """Step 2 for one book: read its state, undo what a crashed tick left in the logs, rotate."""
    sd = t.state_dir
    b = _Book(name=name, cfg=cfg.books[name])
    path = sd / f"{name}.json"
    if path.exists():
        try:
            b.state, b.fp, b.started_bar, b.log_bytes = _parse_state(path, name)
        except Exception as e:
            b.reset()
            dest = retire_book(sd, name, "unreadable", t.tick_utc)
            t.alert("critical", "state_unreadable",
                    f"{name}: the state file could not be read ({type(e).__name__}: {e}). It was moved to {dest} "
                    f"and the book restarts flat.", book=name, detail={"archived_to": str(dest)})
    if b.state is None:
        leftovers = [k for k in LOG_FILES if _log_path(sd, k, name).exists()]
        if leftovers:           # log lines without a state file: a crash before the book's first commit
            dest = retire_book(sd, name, "orphan_logs", t.tick_utc)
            t.alert("warn", "log_rollback", f"{name}: log files without a state file were moved to {dest}",
                    book=name, detail={"archived_to": str(dest), "logs": leftovers})
        return b
    if b.cfg is None:
        b.closing = True
    else:
        strategy, params = load_strategy(b.cfg)
        b.closing = fingerprint(b.cfg, strategy, params, cfg.risk.equity0) != b.fp
    cut, changed = {}, False
    for kind in LOG_FILES:
        p = _log_path(sd, kind, name)
        size = p.stat().st_size if p.exists() else 0
        if size > b.log_bytes[kind]:           # written by a tick that died before its state write
            _truncate(p, b.log_bytes[kind])
            cut[kind] = {"committed": b.log_bytes[kind], "found": size, "cut_bytes": size - b.log_bytes[kind]}
        elif size < b.log_bytes[kind]:         # shorter (moved or rotated by hand): accepted as it is
            b.log_bytes[kind], changed = size, True
    if cut:
        t.alert("warn", "log_rollback", f"{name}: log lines from a tick that did not finish were cut off; "
                                        f"the bar is processed again", book=name, detail=cut)
    if _rotate(sd, f"decisions_{name}", t.tick_utc):
        b.log_bytes["decisions"], changed = 0, True
    if changed:
        _write_state(t, b)
    return b


def _lag(b: _Book, t_end: pd.Timestamp) -> int:
    """Hours from the book's last processed bar to the newest closed bar (0 = up to date)."""
    if b.state is None or not b.state.last_time:
        return 0
    return max(0, int(round((t_end - feed.utc(b.state.last_time)) / HOUR)))


def _summary(b: _Book, t_end: pd.Timestamp | None, status: str, detail: str = "") -> dict:
    st = b.state
    name = b.fp["name"] if b.fp else (b.cfg.module.rsplit(".", 1)[-1] if b.cfg else None)
    if st is None:
        return {"strategy": name, "status": status, "detail": detail, "last_bar": None, "lag_bars": None,
                "equity": None, "day_pnl": None, "positions": 0, "orders": 0, "halted": False, "halt_reason": ""}
    return {"strategy": name, "status": status, "detail": detail, "last_bar": st.last_time or None,
            "lag_bars": None if t_end is None else _lag(b, t_end), "equity": float(st.equity),
            "day_pnl": float(st.equity - st.day_start_equity), "positions": len(st.positions),
            "orders": len(st.orders), "halted": bool(st.halted), "halt_reason": st.halt_reason}


def _engine(cfg: BotConfig, b: _Book, killed: bool) -> Engine:
    risk = dataclasses.replace(cfg.risk, equity0=float(b.fp["equity0"]),
                               halt_sticky=True if killed else cfg.risk.halt_sticky)
    eng = Engine(Costs(), risk, valid_bars=int(b.fp["valid_bars"]), max_hold=int(b.fp["max_hold"]),
                 state=b.state, log_events=True)
    eng.rows = []                          # equity rows of the bars this tick processes
    return eng


def _event(eng: Engine, t: _Tick, kind: str, symbol: str = "*", **detail) -> None:
    eng.events.append({"time": eng.state.last_time or t.now.isoformat(), "symbol": symbol, "event": kind, **detail})


def _apply_halts(t: _Tick, eng: Engine, frozen: bool) -> None:
    """Step 6b: manual kill, its release, and the frozen feed."""
    st = eng.state
    if t.killed:
        guardian.halt(eng, MANUAL_KILL, t.now)
        if st.halt_reason != MANUAL_KILL:
            # the book was already halted for another reason: the kill switch takes the halt over, so that
            # releasing the switch resumes the book (otherwise a sticky halt could never be lifted)
            _event(eng, t, "guardian_halt", reason=f"{MANUAL_KILL} (takes over the halt: {st.halt_reason})")
            st.halt_reason = MANUAL_KILL
    elif st.halted and st.halt_reason == MANUAL_KILL:
        eng.resume()
        _event(eng, t, "resume", reason=REASONS["resume"])
    if frozen:
        guardian.halt(eng, FROZEN_FEED, t.now)


def _bars_to_run(b: _Book, market: _Market | None) -> tuple[int, int]:
    """(i0, i1): positions in the base index of the bars after the book's last one, up to the cap."""
    if market is None or market.base is None:
        return 0, 0
    if not b.state.last_time:
        return max(0, market.i1 - 1), market.i1
    last = feed.utc(b.state.last_time)
    if len(market.base.index) and last + HOUR < market.base.index[0]:
        raise RuntimeError(f"the window starts at {market.base.index[0].isoformat()}, after the bar that follows "
                           f"this book's last bar {b.state.last_time}: bars would be skipped")
    return int(market.base.index.searchsorted(last, side="right")), market.i1


def _run_bars(t: _Tick, eng: Engine, market: _Market, intents: dict, i0: int, i1: int) -> None:
    eng.run(attach(market.base, intents), i0, i1)
    times = [ts.isoformat() for ts in market.base.index[i0:i1]]
    for k, when in enumerate(times):
        eq = eng.equity_curve[i0 + k]
        if not math.isnan(eq):
            eng.rows.append(f"{when},{float(eq)!r},{float(eng.gross_curve[i0 + k])!r},{t.tick_utc}")


def _commit(t: _Tick, b: _Book, eng: Engine) -> None:
    """Step 6e: append the decisions, trades and equity rows, then replace the state file."""
    sd, strat = t.state_dir, b.fp["name"]
    sizes = dict(b.log_bytes)
    if eng.events:
        lines = []
        for ev in eng.events:
            d = {"time": ev["time"], "book": b.name, "strategy": strat, "event": ev["event"], "symbol": ev["symbol"],
                 "reason": ev.get("reason") or REASONS.get(ev["event"], ev["event"])}
            d.update({k: v for k, v in ev.items() if k not in d})
            d["tick_utc"] = t.tick_utc
            lines.append(json.dumps(to_jsonable(d), allow_nan=False))
        sizes["decisions"] = append_lines(_log_path(sd, "decisions", b.name), lines)
    if eng.trades:
        lines = [json.dumps(to_jsonable({**tr, "book": b.name, "strategy": strat, "tick_utc": t.tick_utc}),
                            allow_nan=False) for tr in eng.trades]
        sizes["ledger"] = append_lines(_log_path(sd, "ledger", b.name), lines)
    if eng.rows:
        path = _log_path(sd, "equity", b.name)
        rows = eng.rows if path.exists() and path.stat().st_size > 0 else [EQUITY_HEADER] + eng.rows
        sizes["equity"] = append_lines(path, rows)
    b.log_bytes = sizes
    _write_state(t, b)


def _snapshot(st: State) -> str:
    return json.dumps(to_jsonable(st.to_json()), sort_keys=True)


def _close_out(t: _Tick, cfg: BotConfig, b: _Book, market: _Market | None, frozen: bool) -> bool:
    """Step 6c: flatten a book whose strategy changed. True once it is flat and retired."""
    eng = _engine(cfg, b, t.killed)
    before = _snapshot(eng.state)
    _apply_halts(t, eng, frozen)
    st = eng.state
    for s in list(st.orders):
        del st.orders[s]
        _event(eng, t, "order_cancelled", symbol=s, reason="strategy swap")
    for pos in st.positions.values():
        pos.exit_pending = "strategy_swap"
    i0, i1 = _bars_to_run(b, market)
    if st.positions and i0 < i1:
        _run_bars(t, eng, market, {}, i0, i1)       # blank intents: the engine sells at the next bar's open
    if eng.events or eng.trades or eng.rows or _snapshot(st) != before:
        _commit(t, b, eng)
    if st.positions:
        t.books[b.name] = _summary(b, t.t_end, "closing", "strategy changed: positions are sold at the next bar's open")
        return False
    old = b.fp["name"]
    dest = retire_book(t.state_dir, b.name, "swapped", t.tick_utc)
    t.alert("info", "strategy_changed", f"{b.name}: the config changed, so the {old} book was closed flat and "
                                        f"archived to {dest}", book=b.name, detail={"archived_to": str(dest)})
    b.reset()
    return True


def _advance(t: _Tick, cfg: BotConfig, b: _Book, market: _Market | None, frozen: bool) -> None:
    """Step 6 for one book. Raises on any error; nothing of the book is written unless `_commit` ran."""
    if b.state is not None and b.closing and not _close_out(t, cfg, b, market, frozen):
        return
    if b.cfg is None:
        t.books[b.name] = _summary(b, t.t_end, "empty", "no strategy configured")
        return
    strategy, params = load_strategy(b.cfg)
    new = b.state is None
    if new:
        why = ("the feed is not usable yet" if market is None else
               "waiting for this month in data/universe.json" if market.base is None or market.t_cap != market.t_last
               else "no bar to start on" if market.i1 < 1 else "")
        if why:
            t.books[b.name] = _summary(b, t.t_end, "waiting", why)
            return
        b.fp = fingerprint(b.cfg, strategy, params, cfg.risk.equity0)
        eq0 = float(cfg.risk.equity0)
        b.state = State(cash=eq0, equity=eq0, day_start_equity=eq0)
        b.started_bar = market.base.index[market.i1 - 1].isoformat()
        b.log_bytes = _zero_sizes()
    eng = _engine(cfg, b, t.killed)
    if new:
        eng.events.append({"time": b.started_bar, "symbol": "*", "event": "book_started",
                           "reason": REASONS["book_started"]})
    before = _snapshot(eng.state)
    _apply_halts(t, eng, frozen)
    i0, i1 = _bars_to_run(b, market)
    if i0 < i1:
        intents = strategy.intents({s: df.copy() for s, df in market.data.items()}, params)
        _run_bars(t, eng, market, intents, i0, i1)
        if not new and i1 - i0 > 1:
            t.alert("warn", "missed_bars", f"{b.name}: {i1 - i0} bars were processed in one tick (ticks were missed "
                                           f"or the feed was late); the result equals hourly ticks",
                    book=b.name, detail={"bars": i1 - i0})
    if new or eng.events or eng.trades or eng.rows or _snapshot(eng.state) != before:
        _commit(t, b, eng)
    if i0 < i1:
        t.books[b.name] = _summary(b, t.t_end, "ok", f"processed {i1 - i0} bar(s)")
    else:
        why = ("the feed is not usable: waiting" if market is None else
               "waiting for this month in data/universe.json" if market.t_cap is None or market.t_cap < market.t_last
               else "nothing new")
        t.books[b.name] = _summary(b, t.t_end, "idle", why)


# -------------------------------------------------------------------------- tick
def _run(t: _Tick, config_path, source) -> None:
    sd = t.state_dir
    prev = _read_json(sd / HEARTBEAT)
    try:
        prev_feed_time = feed.utc(prev["feed"]["feed_time"])
    except (TypeError, KeyError, ValueError):
        prev_feed_time = None
    if prev_feed_time is None or pd.isna(prev_feed_time):
        prev_feed_time = None                # no earlier heartbeat, or it never saw a usable feed
    else:
        t.feed["feed_time"] = prev_feed_time.isoformat()
    _rotate(sd, "alerts", t.tick_utc)

    # 1. config, universe, kill switch
    cfg = load_config(config_path)
    store.universe.cache_clear()             # a long-running loop must see an updated universe file
    universe = store.universe()
    t.killed = guardian.kill_requested(cfg, sd)
    if t.killed:
        t.alert("warn", "killed", "kill switch is ON: orders cancelled, positions closed at the next bar, no entries. "
                                  "Remove state/KILL (or set kill: false) to resume.")
    asof = feed.closed_asof(t.now, cfg.settle_seconds)
    t.t_end = asof - HOUR

    # 2. books
    books = {name: _load_book(t, cfg, name) for name in BOOK_NAMES}

    # 3. window
    for b in books.values():
        if b.state is not None and _lag(b, t.t_end) > cfg.max_catchup_bars:
            lag = _lag(b, t.t_end)
            dest = retire_book(sd, b.name, "too_old", t.tick_utc)
            t.alert("critical", "state_too_old",
                    f"{b.name}: its last bar is {lag} hours old, more than max_catchup_bars "
                    f"({cfg.max_catchup_bars}). The book was archived to {dest} and restarts flat.",
                    book=b.name, detail={"lag_bars": lag, "archived_to": str(dest)})
            b.reset()
    for b in books.values():
        t.books[b.name] = _summary(b, t.t_end, "idle" if b.state is not None else "waiting" if b.cfg else "empty")
    live = [b for b in books.values() if b.state is not None]
    max_lag = max([1] + [_lag(b, t.t_end) for b in live])
    start = asof - (cfg.window_bars + max_lag) * HOUR
    held = {s for b in live for s in list(b.state.positions) + list(b.state.orders)}
    # bars of an earlier month that will be replayed need that month's whole universe, not just this month's
    replayed = {s for m in feed.months_between(t.t_end - (max_lag - 1) * HOUR, t.t_end) for s in universe.get(m, ())}
    required, context = feed.symbols_needed(universe, start, asof, held,
                                            tuple(cfg.extra_symbols) + tuple(sorted(replayed)))

    # 4. fetch and pre-flight
    fetched = feed.fetch(source if source is not None else feed.KrakenSource(), required + context, start, asof)
    verdict = guardian.preflight(fetched, required, t.now, asof, cfg, prev_feed_time)
    t.alerts.extend(verdict.alerts)
    t.feed.update(usable=verdict.usable, frozen=verdict.frozen, age_minutes=verdict.age_minutes,
                  symbols=len(fetched.frames), failed=sorted(fetched.errors))
    if verdict.usable:
        t.feed["feed_time"] = verdict.t_last.isoformat()

    # 5. data
    market = None
    if verdict.usable:
        t_last = verdict.t_last
        data, gaps, bad = feed.prepare(fetched.frames, t_last, cfg.delist_after_bars)
        t_cap = guardian.universe_cap(t_last, universe)
        if t_cap is None or t_cap < t_last:
            t.alert("critical", "universe_stale",
                    f"data/universe.json has no entry for {t_last.strftime('%Y-%m')}: bars of that month are not "
                    f"processed. Run `python -m desk.data.download`, commit data/universe.json; the missed bars "
                    f"are then replayed.", detail={"feed_time": t_last.isoformat(),
                                                   "processed_up_to": None if t_cap is None else t_cap.isoformat()})
        watched = held | set(universe.get(t_last.strftime("%Y-%m"), ()))
        needs = {b.name: tuple(load_strategy(b.cfg)[0].needs) for b in books.values() if b.cfg is not None}
        t.alerts.extend(guardian.check_data(data, gaps, bad, watched, needs, t_last, cfg))
        base = feed.build_base(data, t_cap) if t_cap is not None else None
        i1 = 0 if base is None else int(base.index.searchsorted(t_cap, side="right"))
        market = _Market(data=data, base=base, t_last=t_last, t_cap=t_cap, i1=i1)

    # 6. each book in its own try/except, champion first
    for name in BOOK_NAMES:
        b = books[name]
        try:
            _advance(t, cfg, b, market, verdict.frozen)
        except Exception as e:
            t.alert("critical", "book_error",
                    f"{name}: {type(e).__name__}: {e}. Nothing of this book was written this tick; the other "
                    f"books carry on and the bar is processed again next tick.", book=name,
                    detail={"traceback": traceback.format_exc()})
            on_disk = _Book(name=name, cfg=b.cfg)
            try:
                on_disk.state, on_disk.fp, on_disk.started_bar, on_disk.log_bytes = \
                    _parse_state(sd / f"{name}.json", name)
            except Exception:
                pass
            t.books[name] = _summary(on_disk, t.t_end, "error", f"{type(e).__name__}: {e}")


def _finish(t: _Tick, started: float) -> dict:
    """Step 7: alerts, heartbeat, one printed line per book. Never raises."""
    counts = {level: sum(a.level == level for a in t.alerts) for level in guardian.LEVELS}
    hb = {"schema": SCHEMA, "tick_utc": t.tick_utc, "ok": counts["critical"] == 0 and t.error is None,
          "mode": "paper", "killed": t.killed, "seconds": round(time.monotonic() - started, 3), "error": t.error,
          "feed": t.feed, "alerts": counts, "books": t.books}
    hb = to_jsonable(hb)
    try:
        guardian.write_alerts(t.state_dir, t.alerts, t.tick_utc)
        atomic_write_json(t.state_dir / HEARTBEAT, hb)
    except Exception as e:
        hb["ok"] = False
        hb["error"] = f"could not write the tick's results: {type(e).__name__}: {e}"
    try:
        print("\n".join(_tick_lines(hb, t.alerts)))
    except Exception:
        pass
    return hb


def _money(x) -> str:
    return "-" if x is None else f"{x:,.2f}"


def _book_lines(books: dict) -> list[str]:
    out = []
    for name in BOOK_NAMES:
        b = books.get(name)
        if b is None:
            continue
        line = f"  {name:<13}{b.get('strategy') or '-':<28}{b['status']:<8}"
        if b.get("equity") is not None:
            line += (f" last bar {b['last_bar']}  equity {_money(b['equity'])}  day {b['day_pnl']:+,.2f}"
                     f"  {b['positions']} position(s), {b['orders']} order(s)")
            if b.get("halted"):
                line += f"  HALTED: {b['halt_reason']}"
        if b.get("detail"):
            line += f"  [{b['detail']}]"
        out.append(line)
    return out


def _tick_lines(hb: dict, alerts: list) -> list[str]:
    f = hb["feed"]
    age = "" if f.get("age_minutes") is None else f", {f['age_minutes']:.0f} min old"
    head = (f"tick {hb['tick_utc']} paper {'OK' if hb['ok'] else 'FAILED'}"
            f"{'  KILL SWITCH ON' if hb['killed'] else ''}  feed {f.get('feed_time') or 'none'}"
            f" ({'usable' if f['usable'] else 'NOT usable'}{', FROZEN' if f['frozen'] else ''}{age},"
            f" {f['symbols']} symbols)")
    lines = [head] + _book_lines(hb["books"])
    lines += [f"  {a.level.upper():<8} {a.code}: {a.message}" for a in alerts]
    if hb.get("error"):
        lines.append(f"  ERROR    {hb['error']}")
    return lines


def tick(config_path=CONFIG, state_dir=STATE, now: pd.Timestamp | None = None, source=None) -> dict:
    """Process every closed bar the books have not seen yet. Returns the heartbeat; never raises."""
    started = time.monotonic()
    state_dir = Path(state_dir)
    now = _now() if now is None else feed.utc(now)
    t = _Tick(state_dir=state_dir, now=now, tick_utc=now.isoformat(timespec="seconds"))
    none = {level: 0 for level in guardian.LEVELS}
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        got, broke = _take_lock(state_dir, t.tick_utc)
    except Exception as e:
        err = f"cannot use the state directory {state_dir}: {type(e).__name__}: {e}"
        print(f"tick {t.tick_utc} paper FAILED  {err}")
        return {"schema": SCHEMA, "tick_utc": t.tick_utc, "ok": False, "mode": "paper", "error": err,
                "alerts": {**none, "critical": 1}}
    if not got:
        print("another tick is running")
        return {"schema": SCHEMA, "tick_utc": t.tick_utc, "ok": True, "mode": "paper", "error": None,
                "skipped": "another tick is running", "alerts": none}
    try:
        if broke:
            t.alert("warn", "lock_stale", f"a lock older than {LOCK_STALE_MINUTES} minutes was removed: an earlier "
                                          f"tick did not finish")
        try:
            _run(t, config_path, source)
        except ConfigError as e:
            t.error = f"config: {e}"
            t.alert("critical", "config_invalid", f"{config_path}: {e}. Nothing was processed.")
        except Exception as e:
            t.error = f"{type(e).__name__}: {e}"
            t.alert("critical", "tick_error", f"the tick stopped: {type(e).__name__}: {e}. Books already written "
                                              f"this tick stay written; the rest is redone next tick.",
                    detail={"traceback": traceback.format_exc()})
        return _finish(t, started)
    finally:
        try:
            (state_dir / LOCK).unlink()
        except OSError:
            pass


def loop(config_path=CONFIG, state_dir=STATE, source=None, max_ticks: int | None = None) -> None:
    """For an always-on machine: tick, sleep until the next hour + settle_seconds + 30 s, repeat."""
    done = 0
    while True:
        tick(config_path, state_dir, source=source)
        done += 1
        if max_ticks is not None and done >= max_ticks:
            return
        try:
            settle = load_config(config_path).settle_seconds
        except ConfigError:
            settle = 120
        now = _now()
        wake = now.floor("h") + pd.Timedelta(seconds=settle + 30)
        if wake <= now:
            wake += HOUR
        time.sleep(max(1.0, (wake - now).total_seconds()))


def status(state_dir=STATE, now: pd.Timestamp | None = None) -> dict:
    """Is the bot alive and well? {"healthy", "why", "heartbeat", "books"} from the last heartbeat."""
    state_dir = Path(state_dir)
    now = _now() if now is None else feed.utc(now)
    hb = _read_json(state_dir / HEARTBEAT)
    if not isinstance(hb, dict) or "tick_utc" not in hb:
        return {"healthy": False, "why": "no heartbeat: the bot has not run yet (or heartbeat.json is unreadable)",
                "heartbeat": None, "books": {}}
    age = (now - feed.utc(hb["tick_utc"])).total_seconds() / 60.0
    if age > STALE_HEARTBEAT_MINUTES:
        why = f"the last tick ran {age:.0f} minutes ago ({hb['tick_utc']}): the bot is not being woken"
    elif not hb.get("ok"):
        codes = sorted({a["code"] for a in read_log(state_dir, "alerts")
                        if a.get("tick_utc") == hb["tick_utc"] and a.get("level") == "critical"})
        why = "the last tick failed: " + (hb.get("error") or "critical alert(s): " + ", ".join(codes))
        if hb.get("error") and codes:
            why += f" ({', '.join(codes)})"
    else:
        why = "ok"
    return {"healthy": why == "ok", "why": why, "heartbeat": hb, "books": hb.get("books") or {}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m desk.bot.paper", description="Paper-trading bot (paper only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("tick", "process the newest closed bar once"), ("loop", "tick every hour, forever"),
                       ("status", "is the bot alive and well?")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--state", default=STATE, help="state directory (default: state)")
        if name != "status":
            p.add_argument("--config", default=CONFIG, help="config file (default: config/bot.yaml)")
        else:
            p.add_argument("--json", action="store_true", help="print the raw status as JSON")
    args = ap.parse_args(argv)
    if args.cmd == "tick":
        return 0 if tick(args.config, args.state).get("ok") else 1
    if args.cmd == "loop":
        loop(args.config, args.state)
        return 0
    st = status(args.state)
    if args.json:
        print(json.dumps(st, indent=1))
    else:
        print(("HEALTHY" if st["healthy"] else "NOT HEALTHY") + f": {st['why']}")
        hb = st["heartbeat"]
        if hb:
            f = hb.get("feed") or {}
            print(f"last tick {hb['tick_utc']}  mode {hb.get('mode')}  kill switch {'ON' if hb.get('killed') else 'off'}"
                  f"  feed {f.get('feed_time') or 'none'}")
            print("\n".join(_book_lines(st["books"])))
    return 0 if st["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
