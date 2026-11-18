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

Where this file goes beyond docs/BOT_SPEC.md (changes made after the review):
  * the venue clock is read before any book is retired or any bar is fetched;
    with a clock that is wrong or unreadable no book is retired, and with a
    wrong clock none is halted either;
  * a catch-up tick replays the missed bars under the state as it was stored
    and applies the kill switch, its release, a frozen-feed halt or a strategy
    swap only before the newest bar: the same result as hourly ticks;
  * an unusable feed is aged from what the bot saw while awake (heartbeat
    `feed.unusable_since`) and is frozen only from the second unusable tick in a
    row, so one failed fetch (after a scheduler pause, or on a run that starts
    late in the hour) is not a frozen feed, and a feed that never worked becomes one;
  * a required symbol that cannot be fetched for `delist_after_bars` hours while
    BTC can (heartbeat `feed.failing_since`) is treated as delisted;
  * a held symbol's newest bar may lag BTC's by one tick before it is accepted
    as missing;
  * challenger books keep their slot when the `challengers` list is reordered;
  * the Guardian's own loss halts raise the alert `guardian_halt`.
  * a new book whose strategy has no entry signal anywhere in the window raises `strategy_silent`
    (the sign of a strategy that needs more history than `feed.window_bars`).
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
from ..engine.core import Costs, Engine, Feed, FeedBase, State, attach
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


def _archive_dir(state_dir: Path, book: str, why: str, tick_utc: str) -> Path:
    """Create and return a new folder archive/<book>.<stamp>.<why>/."""
    dest = Path(state_dir) / "archive" / f"{book}.{_stamp(tick_utc)}.{why}"
    n = 1
    while dest.exists():
        n += 1
        dest = Path(state_dir) / "archive" / f"{book}.{_stamp(tick_utc)}.{why}-{n}"
    dest.mkdir(parents=True)
    return dest


def retire_book(state_dir: Path, book: str, why: str, tick_utc: str, dest: Path | None = None) -> Path:
    """Move a book's files to archive/<book>.<stamp>.<why>/: the logs first, the state file last, so a
    crash in between leaves a state file whose (missing) logs are simply accepted as shorter."""
    state_dir = Path(state_dir)
    if dest is None:
        dest = _archive_dir(state_dir, book, why, tick_utc)
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
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < LOCK_STALE_MINUTES * 60:
                return False, broke
            # break the stale lock by renaming it: of several starters only one rename can succeed
            aside = path.with_name(f"tick.{os.getpid()}.{time.monotonic_ns()}.stale.lock")
            try:
                os.rename(path, aside)
            except FileNotFoundError:
                continue                             # another starter broke it first
            if time.time() - aside.stat().st_mtime < LOCK_STALE_MINUTES * 60:
                os.rename(aside, path)               # a live lock had taken its place meanwhile: give it back
                return False, broke
            aside.unlink(missing_ok=True)
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
    cfg: BookConfig | None = None          # what the config asks for (None = no strategy)
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
                                                "age_minutes": None, "symbols": 0, "failed": [],
                                                "unusable_since": None, "failing_since": {}})
    killed: bool = False
    error: str | None = None
    t_end: pd.Timestamp | None = None
    written: int = 0                                   # alerts already appended to alerts.jsonl

    def alert(self, level: str, code: str, message: str, book: str = "", symbol: str = "",
              detail: dict | None = None) -> None:
        self.alerts.append(Alert(level, code, message, book, symbol, detail))

    def flush(self) -> None:
        """Append the alerts raised so far to alerts.jsonl (may raise; `_finish` reports that)."""
        guardian.write_alerts(self.state_dir, self.alerts[self.written:], self.tick_utc)
        self.written = len(self.alerts)

    def flush_now(self) -> None:
        """Before files are moved: an alert that explains the move must not be lost if the tick dies."""
        try:
            self.flush()
        except Exception:
            pass                                       # `_finish` tries again and reports the failure


def _is_number(v, nan_ok: bool = False) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return math.isfinite(v) or (nan_ok and v != v)


def _parse_state(path: Path, name: str) -> tuple[State, dict, str, dict]:
    """Read a book's state file. OSError if the file cannot be read; any other exception if what was read
    is not a sound schema-1 state of this book."""
    return _parse_doc(Path(path).read_bytes(), name)


def _parse_doc(raw: bytes, name: str) -> tuple[State, dict, str, dict]:
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"not a schema {SCHEMA} state file")
    if doc.get("book") != name:
        raise ValueError(f"the file belongs to book {doc.get('book')!r}")
    st = State.from_json(doc["engine"])
    if not all(_is_number(v) for v in (st.cash, st.equity, st.day_start_equity, st.day, st.consec_losses,
                                       st.halt_day, st.n_trades)):
        raise ValueError("the engine state holds a value that is not a number")
    if not isinstance(st.last_time, str) or not isinstance(st.halt_reason, str) or not isinstance(st.halted, bool):
        raise ValueError("last_time, halt_reason or halted has the wrong type")
    if st.last_time:
        feed.utc(st.last_time)                              # raises if it is not a time
    for pos in st.positions.values():
        fixed = (pos.side, pos.qty, pos.entry_price, pos.stop, pos.stop0, pos.risk_usd, pos.fees, pos.funding,
                 pos.bars_held, pos.last_price)
        if not all(_is_number(v) for v in fixed) or not _is_number(pos.tp, nan_ok=True) \
                or not isinstance(pos.exit_pending, str) or pos.side not in (1, -1):
            raise ValueError(f"the position in {pos.symbol} holds a value that is not a number")
    for od in st.orders.values():
        if not all(_is_number(v) for v in (od.side, od.stop, od.valid_left)) \
                or not _is_number(od.limit, nan_ok=True) or not _is_number(od.tp, nan_ok=True):
            raise ValueError(f"the order in {od.symbol} holds a value that is not a number")
    fp = doc["strategy"]
    absent = [k for k in ("module", "name", "params", "valid_bars", "max_hold", "equity0") if k not in fp]
    if absent or not isinstance(fp["params"], dict):
        raise ValueError(f"the strategy fingerprint is incomplete: {absent or 'params'}")
    fp["valid_bars"], fp["max_hold"], fp["equity0"] = int(fp["valid_bars"]), int(fp["max_hold"]), float(fp["equity0"])
    sizes = {k: int(doc["log_bytes"][k]) for k in LOG_FILES}
    if min(sizes.values()) < 0:
        raise ValueError("a committed log size is negative")
    started = str(doc["started_bar"])
    feed.utc(started)
    return st, fp, started, sizes


def _write_state(t: _Tick, b: _Book) -> None:
    atomic_write_json(t.state_dir / f"{b.name}.json", {
        "schema": SCHEMA, "book": b.name, "started_bar": b.started_bar, "updated_utc": t.tick_utc,
        "engine": b.state.to_json(), "strategy": b.fp, "log_bytes": b.log_bytes})


def _truncate(path: Path, size: int) -> None:
    with open(path, "r+b") as f:
        f.truncate(size)
        f.flush()
        os.fsync(f.fileno())


def _load_book(t: _Tick, name: str) -> _Book:
    """Step 2 for one book: read its state, undo what a crashed tick left in the logs, rotate.
    What the config wants for the book (`cfg`, `closing`) is decided afterwards by `_assign`."""
    sd = t.state_dir
    b = _Book(name=name)
    path = sd / f"{name}.json"
    try:
        raw = path.read_bytes()            # any other OSError fails the tick: the file itself may be fine
    except FileNotFoundError:
        raw = None
    if raw is not None:
        try:
            b.state, b.fp, b.started_bar, b.log_bytes = _parse_doc(raw, name)
        except Exception as e:
            b.reset()
            dest = _archive_dir(sd, name, "unreadable", t.tick_utc)
            t.alert("critical", "state_unreadable",
                    f"{name}: the state file could not be read ({type(e).__name__}: {e}). It was moved to {dest} "
                    f"and the book restarts flat.", book=name, detail={"archived_to": str(dest)})
            t.flush_now()
            retire_book(sd, name, "unreadable", t.tick_utc, dest)
    if b.state is None:
        leftovers = [k for k in LOG_FILES if _log_path(sd, k, name).exists()]
        if leftovers:           # log lines without a state file: a crash before the book's first commit
            dest = retire_book(sd, name, "orphan_logs", t.tick_utc)
            t.alert("warn", "log_rollback", f"{name}: log files without a state file were moved to {dest}",
                    book=name, detail={"archived_to": str(dest), "logs": leftovers})
        return b
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


def _assign(cfg: BotConfig, books: dict) -> None:
    """Give every book its config entry and decide which books are closing (the config no longer matches).

    A challenger keeps the slot its book already runs in, wherever its entry now sits in the `challengers`
    list: promoting or removing the first challenger must not restart the second one's record."""
    one, two = books["challenger_1"], books["challenger_2"]
    c1, c2 = cfg.books["challenger_1"], cfg.books["challenger_2"]

    def runs_in(c: BookConfig | None, b: _Book) -> bool:
        return c is not None and b.fp is not None and fingerprint(c, *load_strategy(c), cfg.risk.equity0) == b.fp

    if not runs_in(c1, one) and not runs_in(c2, two) and (runs_in(c1, two) or runs_in(c2, one)):
        c1, c2 = c2, c1
    books["champion"].cfg = cfg.books["champion"]
    one.cfg = None if c1 is None else dataclasses.replace(c1, name=one.name)
    two.cfg = None if c2 is None else dataclasses.replace(c2, name=two.name)
    for b in books.values():
        b.closing = b.state is not None and not runs_in(b.cfg, b)


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


def _engine(cfg: BotConfig, b: _Book, sticky: bool) -> Engine:
    risk = dataclasses.replace(cfg.risk, equity0=float(b.fp["equity0"]),
                               halt_sticky=True if sticky else cfg.risk.halt_sticky)
    eng = Engine(Costs(), risk, valid_bars=int(b.fp["valid_bars"]), max_hold=int(b.fp["max_hold"]),
                 state=b.state, log_events=True)
    eng.rows = []                          # equity rows of the bars this tick processes
    return eng


def _stored_kill(b: _Book) -> bool:
    """The book was halted by the kill switch on an earlier tick: that halt has no end date."""
    return bool(b.state.halted) and b.state.halt_reason == MANUAL_KILL


def _event(eng: Engine, t: _Tick, kind: str, symbol: str = "*", **detail) -> None:
    eng.events.append({"time": eng.state.last_time or t.now.isoformat(), "symbol": symbol, "event": kind, **detail})


def _apply_halts(t: _Tick, b: _Book, eng: Engine, frozen: bool) -> None:
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
        t.alert("info", "resumed", f"{b.name}: the kill switch was released, the book may trade again. Any halt it "
                                   f"was under is cleared and its loss count for the day starts again from here.",
                book=b.name)
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


def _run_bars(t: _Tick, eng: Engine, bars: Feed, i0: int, i1: int) -> None:
    eng.run(bars, i0, i1)
    for k in range(i0, i1):
        eq = eng.equity_curve[k]
        if not math.isnan(eq):
            eng.rows.append(f"{bars.times[k]},{float(eq)!r},{float(eng.gross_curve[k])!r},{t.tick_utc}")


def _play(t: _Tick, cfg: BotConfig, b: _Book, eng: Engine, replay: Feed | None, newest: Feed | None,
          i0: int, i1: int, frozen: bool, swap: bool = False) -> None:
    """Steps 6b to 6d. The missed bars (all but the newest) are replayed under the state as it was stored.
    Only then does the book learn what THIS tick knows (the kill switch or its release, a frozen feed, a
    strategy swap), and the newest bar is run with that. A halt or a swap is therefore never filled at a
    price from hours before it was asked for, and a late tick gives the same result as hourly ticks."""
    if i1 - i0 > 1:
        _run_bars(t, eng, replay, i0, i1 - 1)
    eng.risk = dataclasses.replace(eng.risk, halt_sticky=True if t.killed else cfg.risk.halt_sticky)
    _apply_halts(t, b, eng, frozen)
    st = eng.state
    if swap:
        for s in list(st.orders):
            del st.orders[s]
            _event(eng, t, "order_cancelled", symbol=s, reason="strategy swap")
        for pos in st.positions.values():
            pos.exit_pending = "strategy_swap"
    if i0 < i1 and (st.positions or not swap):      # a flat book that is being retired needs no further bar
        _run_bars(t, eng, newest, i1 - 1, i1)


def _commit(t: _Tick, b: _Book, eng: Engine) -> None:
    """Step 6e: append the decisions, trades and equity rows, then replace the state file."""
    sd, strat = t.state_dir, b.fp["name"]
    if not (math.isfinite(b.state.cash) and math.isfinite(b.state.equity)):
        raise ValueError(f"cash {b.state.cash!r} / equity {b.state.equity!r} is not a number: the book is not "
                         f"written (a price that is not a number reached the engine)")
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


def _loss_halt_alerts(t: _Tick, cfg: BotConfig, b: _Book, eng: Engine) -> None:
    """The Guardian's own halts (-3% on the day, losing streak) are what the owner most needs to hear about.
    Critical for the champion, so the run is marked failed and the owner is notified; a warning for the
    shadow books. Kill-switch and frozen-feed halts have their own alerts."""
    for ev in eng.events:
        reason = str(ev.get("reason") or "")
        if ev["event"] != "guardian_halt" or reason.startswith((MANUAL_KILL, FROZEN_FEED)):
            continue
        t.alert("critical" if b.name == "champion" else "warn", "guardian_halt",
                f"{b.name}: the Guardian halted the book at bar {ev['time']}: {reason}. Its orders are cancelled, "
                f"its positions are closed at the next bar's open and it opens nothing"
                + (" until the kill switch is switched on and off again (halt_sticky is set)."
                   if cfg.risk.halt_sticky else " until the next UTC day."),
                book=b.name, detail={"bar": ev["time"], "reason": reason})


def _snapshot(st: State) -> str:
    return json.dumps(to_jsonable(st.to_json()), sort_keys=True)


def _data_copy(market: _Market) -> dict:
    return {s: df.copy() for s, df in market.data.items()}


def _close_out(t: _Tick, cfg: BotConfig, b: _Book, market: _Market | None, frozen: bool) -> bool:
    """Step 6c: flatten a book whose strategy changed. True once it is flat and retired."""
    eng = _engine(cfg, b, _stored_kill(b))
    before = _snapshot(eng.state)
    st = eng.state
    i0, i1 = _bars_to_run(b, market)
    replay = blank = None
    if i0 < i1:
        replay = blank = attach(market.base, {})    # blank intents: the engine sells at the next bar's open
    if i1 - i0 > 1:                                 # hours missed before the swap: the old strategy still ran them
        try:
            old, params = load_strategy(BookConfig(name=b.name, module=b.fp["module"], params=dict(b.fp["params"])))
            replay = attach(market.base, old.intents(_data_copy(market), params))
        except Exception as e:
            t.alert("warn", "missed_bars", f"{b.name}: the strategy being retired ({b.fp['name']}) could not be run "
                                           f"for the {i1 - i0 - 1} missed bar(s) ({type(e).__name__}: {e}); they "
                                           f"were replayed with its stops and targets only", book=b.name)
    _play(t, cfg, b, eng, replay, blank, i0, i1, frozen, swap=True)
    if eng.events or eng.trades or eng.rows or _snapshot(st) != before:
        _commit(t, b, eng)
    _loss_halt_alerts(t, cfg, b, eng)
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
    eng = _engine(cfg, b, _stored_kill(b))
    if new:
        eng.events.append({"time": b.started_bar, "symbol": "*", "event": "book_started",
                           "reason": REASONS["book_started"]})
    before = _snapshot(eng.state)
    i0, i1 = _bars_to_run(b, market)
    bars, trouble = None, ""
    if i0 < i1:
        try:
            bars = attach(market.base, strategy.intents(_data_copy(market), params))
        except Exception as e:
            if new or not (t.killed or frozen):
                raise
            # the book must be flattened NOW (kill switch or frozen feed) and entries are blocked anyway:
            # a failing strategy must not stand in the way, so the bars run without its signals
            trouble, trace = f"{type(e).__name__}: {e}", traceback.format_exc()
            bars = attach(market.base, {})
            t.alert("critical", "book_error",
                    f"{b.name}: {trouble}. The book is being flattened ({MANUAL_KILL if t.killed else FROZEN_FEED}), "
                    f"so its bars were processed without the strategy's signals.", book=b.name,
                    detail={"traceback": trace})
        if new and not any(f.side.any() for f in bars.sym.values()):
            # e.g. a strategy that ranks against more history than feed.window_bars: it would never trade,
            # and nothing else would ever say so. The bot cannot tell that from a market without setups.
            t.alert("warn", "strategy_silent",
                    f"{b.name}: {b.fp['name']} gives no entry signal anywhere in the {len(market.base.index)} hours "
                    f"of history the bot holds ({len(bars.sym)} symbols). That is harmless if the market simply gave "
                    f"it no setup, but a strategy that needs more history than feed.window_bars ({cfg.window_bars}) "
                    f"looks exactly like this and never trades: make sure the window check in docs/RUNBOOK.md "
                    f"passes for it.", book=b.name,
                    detail={"window_bars": cfg.window_bars, "bars": len(market.base.index), "symbols": len(bars.sym)})
    _play(t, cfg, b, eng, bars, bars, i0, i1, frozen)
    if not new and i1 - i0 > 1:
        t.alert("warn", "missed_bars", f"{b.name}: {i1 - i0} bars were processed in one tick (ticks were missed "
                                       f"or the feed was late); the result equals hourly ticks",
                book=b.name, detail={"bars": i1 - i0})
    if new or eng.events or eng.trades or eng.rows or _snapshot(eng.state) != before:
        _commit(t, b, eng)
    _loss_halt_alerts(t, cfg, b, eng)
    if trouble:
        t.books[b.name] = _summary(b, t.t_end, "error", f"{trouble}; processed {i1 - i0} bar(s) without the strategy")
    elif i0 < i1:
        t.books[b.name] = _summary(b, t.t_end, "ok", f"processed {i1 - i0} bar(s)")
    else:
        why = ("the feed is not usable: waiting" if market is None else
               "waiting for this month in data/universe.json" if market.t_cap is None or market.t_cap < market.t_last
               else "the newest bar is not published yet: waiting" if b.state.last_time and t.t_end is not None
               and feed.utc(b.state.last_time) < t.t_end else "nothing new")
        t.books[b.name] = _summary(b, t.t_end, "idle", why)


def _halt_only(t: _Tick, cfg: BotConfig, name: str, frozen: bool) -> None:
    """A book could not be processed while the kill switch is on or the feed is frozen: at least put the
    halt on record (orders cancelled, positions flagged for sale, entries blocked). No bar is run."""
    b = _load_book(t, name)
    if b.state is None:
        return
    eng = _engine(cfg, b, True)
    before = _snapshot(eng.state)
    _apply_halts(t, b, eng, frozen)
    if _snapshot(eng.state) != before:
        _commit(t, b, eng)


# -------------------------------------------------------------------------- tick
def _time_or_none(value) -> pd.Timestamp | None:
    try:
        ts = feed.utc(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(ts) else ts


def _failing(t: _Tick, cfg: BotConfig, fetched: feed.Fetched, required: list[str], since: dict) -> tuple[dict, dict]:
    """({symbol: clock time its fetch first failed}, {symbol: hours} of those failing for delist_after_bars
    hours or more). A run of failures only starts on a tick where BTC itself was fetched: when everything
    fails the venue is down, which says nothing about one symbol. BTC is never given up: it is the clock."""
    btc_ok = feed.BTC in fetched.frames
    failing = {}
    for s in required:
        if s in fetched.frames:
            continue
        first = since.get(s)
        if first is None or first > t.now:
            if not btc_ok:
                continue
            first = t.now
        failing[s] = first
    dead = {s: (t.now - first) / HOUR for s, first in failing.items()
            if btc_ok and s != feed.BTC and t.now - first >= cfg.delist_after_bars * HOUR}
    return failing, dead


def _run(t: _Tick, config_path, source) -> None:
    sd = t.state_dir
    prev = _read_json(sd / HEARTBEAT)
    seen = prev.get("feed") if isinstance(prev, dict) and isinstance(prev.get("feed"), dict) else {}
    prev_feed_time = _time_or_none(seen.get("feed_time"))     # None: no earlier heartbeat, or never a usable feed
    unusable_since = _time_or_none(seen.get("unusable_since"))
    raw = seen.get("failing_since") if isinstance(seen.get("failing_since"), dict) else {}
    failing = {str(s): ts for s, ts in ((s, _time_or_none(v)) for s, v in raw.items()) if ts is not None}
    # what the last tick knew is kept until this tick knows better (a tick that stops early changes nothing)
    t.feed["feed_time"] = None if prev_feed_time is None else prev_feed_time.isoformat()
    t.feed["unusable_since"] = None if unusable_since is None else unusable_since.isoformat()
    t.feed["failing_since"] = {s: ts.isoformat() for s, ts in failing.items()}
    t.killed = guardian.kill_file(sd) is not None             # seen even if the config cannot be read
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
    books = {name: _load_book(t, name) for name in BOOK_NAMES}
    _assign(cfg, books)

    # the venue's clock, before anything is decided on this machine's clock
    source = source if source is not None else feed.KrakenSource()
    clock = feed.venue_clock(source)
    clock_ok = guardian.check_clock(clock[0], clock[1], t.now, cfg)[0] == "ok"

    # 3. window
    for b in books.values():
        if clock_ok and b.state is not None and _lag(b, t.t_end) > cfg.max_catchup_bars:
            lag = _lag(b, t.t_end)
            dest = _archive_dir(sd, b.name, "too_old", t.tick_utc)
            t.alert("critical", "state_too_old",
                    f"{b.name}: its last bar is {lag} hours old, more than max_catchup_bars "
                    f"({cfg.max_catchup_bars}). The book was archived to {dest} and restarts flat.",
                    book=b.name, detail={"lag_bars": lag, "archived_to": str(dest)})
            t.flush_now()
            retire_book(sd, b.name, "too_old", t.tick_utc, dest)
            b.reset()
    for b in books.values():
        t.books[b.name] = _summary(b, t.t_end, "idle" if b.state is not None else "waiting" if b.cfg else "empty")
    live = [b for b in books.values() if b.state is not None]
    held = {s for b in live for s in list(b.state.positions) + list(b.state.orders)}

    # 4. fetch and pre-flight
    fetched = feed.Fetched(server_time=clock[0], server_time_delay=clock[1])
    required, dead = [], {}
    if clock_ok:                             # with a doubtful clock "the last closed hour" means nothing
        max_lag = max([1] + [_lag(b, t.t_end) for b in live])
        start = asof - (cfg.window_bars + max_lag) * HOUR
        # bars of an earlier month that will be replayed need that month's whole universe, not just this month's
        replayed = {s for m in feed.months_between(t.t_end - (max_lag - 1) * HOUR, t.t_end)
                    for s in universe.get(m, ())}
        required, context = feed.symbols_needed(universe, start, asof, held,
                                                tuple(cfg.extra_symbols) + tuple(sorted(replayed)))
        fetched = feed.fetch(source, required + context, start, asof, clock=clock)
        t.feed.update(symbols=len(fetched.frames), failed=sorted(fetched.errors))
        failing, dead = _failing(t, cfg, fetched, required, failing)
        t.feed["failing_since"] = {s: ts.isoformat() for s, ts in failing.items()}
        for s, hours in sorted(dead.items()):
            t.alert("warn", "symbol_delisted",
                    f"{s} could not be fetched for {hours:.0f} hours (limit {cfg.delist_after_bars}): treated as "
                    f"delisted. Positions in it are closed at their last price, its orders cancelled, and the "
                    f"other symbols carry on. The bot keeps asking for it.", symbol=s,
                    detail={"hours_failing": hours, "error": fetched.errors.get(s)})
    judged = dataclasses.replace(fetched, errors={s: e for s, e in fetched.errors.items() if s not in dead})
    verdict = guardian.preflight(judged, [s for s in required if s not in dead], t.now, asof, cfg, prev_feed_time,
                                 unusable_since, held - set(dead))
    t.alerts.extend(verdict.alerts)
    t.feed.update(usable=verdict.usable, frozen=verdict.frozen, age_minutes=verdict.age_minutes,
                  unusable_since=None if verdict.unusable_since is None else verdict.unusable_since.isoformat())
    if verdict.usable:
        t.feed["feed_time"] = verdict.t_feed.isoformat()

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
        # a held symbol the venue no longer answers for: the engine is shown that it has no bar any more
        ghosts = {}
        for b in live:
            for s in dead:
                if s in b.state.positions:
                    ghosts[s] = b.state.positions[s].last_price
                elif s in b.state.orders:
                    ghosts.setdefault(s, b.state.orders[s].stop)
        base = feed.build_base(data, t_cap, ghosts) if t_cap is not None else None
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
            if t.killed or verdict.frozen:
                try:
                    _halt_only(t, cfg, name, verdict.frozen)
                except Exception as e2:
                    t.alert("critical", "book_error", f"{name}: the halt could not be recorded either: "
                                                      f"{type(e2).__name__}: {e2}", book=name)
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
    problems = []
    try:
        t.flush()
    except Exception as e:
        problems.append(f"could not write the alert log: {type(e).__name__}: {e}")
    if problems:                             # the heartbeat must say so even when the alert log cannot
        hb["ok"] = False
        hb["error"] = "; ".join(filter(None, [hb["error"]] + problems))
    try:
        atomic_write_json(t.state_dir / HEARTBEAT, hb)
    except Exception as e:
        hb["ok"] = False
        hb["error"] = "; ".join(filter(None, [hb["error"], f"could not write the heartbeat: {type(e).__name__}: {e}"]))
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
    head = (f"tick {hb['tick_utc']} paper {'OK' if hb['ok'] else 'FAILED' if hb.get('error') else 'CRITICAL ALERT'}"
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
            t.alert("critical", "config_invalid", f"{config_path}: {e}. Nothing was processed."
                    + (" The KILL file was seen: with a broken config nothing trades at all, and the kill "
                       "takes effect on the first tick after the config is fixed." if t.killed else ""))
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


def _trading(hb: dict) -> str:
    """One line on whether anything is actually trading: a healthy bot may still be doing nothing."""
    books = hb.get("books") or {}
    champ = books.get("champion") or {}
    shadows = sum(1 for n in BOOK_NAMES[1:] if (books.get(n) or {}).get("strategy"))
    extra = f" ({shadows} challenger book(s) running)" if shadows else ""
    if hb.get("killed"):
        return "nothing: the kill switch is ON"
    if not champ.get("strategy") or champ.get("status") == "empty":
        return "nothing: no champion strategy is configured (champion: null in config/bot.yaml)" + extra
    name = champ["strategy"]
    if champ.get("halted"):
        return f"champion {name} is HALTED by the Guardian: {champ.get('halt_reason')}" + extra
    if champ.get("status") in ("waiting", "error", "closing"):
        return f"champion {name} is not trading yet: {champ['status']} ({champ.get('detail') or 'no detail'})" + extra
    return f"champion {name}, {champ.get('positions', 0)} position(s), {champ.get('orders', 0)} order(s)" + extra


def status(state_dir=STATE, now: pd.Timestamp | None = None) -> dict:
    """Is the bot alive and well? {"healthy", "why", "trading", "heartbeat", "books"} from the last heartbeat."""
    state_dir = Path(state_dir)
    now = _now() if now is None else feed.utc(now)
    hb = _read_json(state_dir / HEARTBEAT)
    if not isinstance(hb, dict) or "tick_utc" not in hb:
        return {"healthy": False, "why": "no heartbeat: the bot has not run yet (or heartbeat.json is unreadable)",
                "trading": "nothing", "heartbeat": None, "books": {}}
    age = (now - feed.utc(hb["tick_utc"])).total_seconds() / 60.0
    seen = hb.get("feed") or {}
    if age > STALE_HEARTBEAT_MINUTES:
        why = f"the last tick ran {age:.0f} minutes ago ({hb['tick_utc']}): the bot is not being woken"
    elif not hb.get("ok"):
        codes = sorted({a["code"] for a in read_log(state_dir, "alerts")
                        if a.get("tick_utc") == hb["tick_utc"] and a.get("level") == "critical"})
        if hb.get("error"):
            why = f"the last tick failed: {hb['error']}" + (f" ({', '.join(codes)})" if codes else "")
        else:
            why = "the last tick raised critical alert(s): " + (", ".join(codes) or "see alerts.jsonl")
    elif not seen.get("usable") and not seen.get("feed_time"):
        why = "the bot has never had usable market data: no bar has been processed yet (see alerts.jsonl)"
    else:
        why = "ok"
    return {"healthy": why == "ok", "why": why, "trading": _trading(hb), "heartbeat": hb,
            "books": hb.get("books") or {}}


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
        print(f"Trading: {st['trading']}")
        hb = st["heartbeat"]
        if hb:
            f = hb.get("feed") or {}
            print(f"last tick {hb['tick_utc']}  mode {hb.get('mode')}  kill switch {'ON' if hb.get('killed') else 'off'}"
                  f"  feed {f.get('feed_time') or 'none'}")
            print("\n".join(_book_lines(st["books"])))
    return 0 if st["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
