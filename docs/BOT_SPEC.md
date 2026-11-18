# Paper bot: spec and architecture

Status: **paper trading only**. No code path in this repo can place a real order and no API key appears
anywhere. The only network code is `desk/bot/feed.py: KrakenSource`, which sends unauthenticated GETs to
Kraken's public market-data API through `desk.data.kraken.KrakenFutures`.

## What it must do (from the desk owner's brief)
1. Trade the champion strategy on paper, nonstop, on live Kraken Futures prices.
2. Send limit orders with a stop attached (simulated against the next real bars).
3. Record every decision with its reason.
4. Recover by itself after any crash.
5. Swap strategies through one config file.
6. Guardian: check every order before it is placed; kill everything at -3% on the day, three losses in a row, or a frozen data feed.
7. Keep two challengers on standby (shadow books) so a challenger can replace the champion after 7 winning paper days.

## Constraints that shaped the design
- The cloud can only wake the bot about once an hour, so the bot is a **stateless hourly tick**, not a
  long-running process. One tick = one closed 1-hour bar. A loop mode exists for an always-on machine.
- Backtest and paper results must be comparable, so the tick drives the **same `desk.engine.core.Engine`**
  the backtests use, one new bar at a time, with `Costs()` and the backtests' `Risk()` defaults and the state
  saved between ticks. The engine test `test_state_round_trips_through_json_and_resumes_identically` pins this.
- A crash must never corrupt a book. Each book is one transaction: append its log lines, then replace its
  state file atomically (temp file, fsync, `os.replace`). The state file records the committed byte size of
  each log, so lines left by a crashed tick are cut off before the bar is redone: nothing is logged twice.
- When data is late, missing or doubtful the bot **waits and replays** instead of guessing. Bars are real
  history, so a bar processed late gives exactly the result it would have given on time.

## Files
| File | Role |
|---|---|
| `config/bot.yaml` | the one config file: mode, kill, account, champion, challengers, Guardian limits, feed |
| `desk/bot/config.py`, `feed.py`, `guardian.py`, `paper.py`, `report.py` | the code; roles and signatures under Interfaces |
| `state/<book>.json` | one book (`champion`, `challenger_1`, `challenger_2`): engine state, strategy fingerprint, committed log sizes |
| `state/decisions_<book>.jsonl`, `ledger_<book>.jsonl`, `equity_<book>.csv` | every decision with its reason; closed trades; one equity row per processed bar (all append-only) |
| `state/alerts.jsonl`, `state/heartbeat.json` | Guardian alerts (append-only); result of the last tick |
| `state/KILL`, `state/tick.lock` | manual kill switch (same as `kill: true`); held while a tick runs (git-ignored) |
| `state/archive/` | retired books (`<book>.<stamp>.<why>/`) and rotated logs (`rotated/`) |

## config/bot.yaml
Every key except `mode` is optional and defaults to the value shown. `ConfigError` on: an unknown key, a `mode`
other than `paper`, more than two challengers, a parameter the strategy does not define, a strategy that is not a
module under `desk.strategies.` exposing `STRATEGY`, a key containing `key`, `secret`, `token` or `password`, or
`risk_per_trade` or a `guardian` number looser than the value shown (they may only be tightened).
```yaml
mode: paper              # the only accepted value
kill: false              # true = cancel orders, flatten, block entries (same as creating state/KILL)
account: {equity0: 10000, risk_per_trade: 0.005}        # per book
champion: null           # or {strategy: desk.strategies.s_name, params: {n: 96}}; null = the book stays flat
challengers: []          # up to 2 entries shaped like champion -> challenger_1, challenger_2
guardian: {daily_loss_limit: 0.03, max_consec_losses: 3, halt_sticky: false, max_pos_mult: 1.0,
           max_gross_mult: 3.0, max_positions: 10, min_stop_pct: 0.002, max_stop_pct: 0.25}   # engine Risk
feed:
  window_bars: 3000            # history given to strategies (125 days), see Tests
  settle_seconds: 120          # a bar counts as closed this long after its hour ends
  extra_symbols: []            # fetched in addition to BTC, ETH and the universe
  stale_feed_minutes: 90       # a feed older than this is frozen
  max_clock_skew_seconds: 30
  delist_after_bars: 72        # hours without a candle before a symbol counts as delisted
  max_catchup_bars: 2000       # longest outage that is replayed
```

## Interfaces (every function that touches state takes the state directory; tests pass `tmp_path`)
```python
# desk/bot/config.py: load and validate the config, import strategies; refuses anything but `mode: paper`
BOOK_NAMES = ("champion", "challenger_1", "challenger_2")
class BookConfig   # frozen dataclass: name: str, module: str, params: dict
class BotConfig    # frozen dataclass: kill: bool, risk: Risk (from account + guardian), books: dict[str, BookConfig | None]
                   # keyed by BOOK_NAMES, and each `feed` key as a field of the same name (extra_symbols as a tuple)
def load_config(path="config/bot.yaml") -> BotConfig                         # raises ConfigError(ValueError)
def load_strategy(book: BookConfig) -> tuple[Strategy, dict]                 # (module.STRATEGY, its params | book.params)
def fingerprint(book: BookConfig, strategy: Strategy, params: dict, equity0: float) -> dict   # "strategy" in the state file
# desk/bot/feed.py: closed hourly bars per symbol in the research column layout, funding fill, gap handling
class KrakenSource:                                  # the default `source`; tests pass any object with these two methods
    def __init__(self, timeout: float = 15.0, max_retries: int = 4)
    def server_time(self) -> pd.Timestamp | None                             # `serverTime` of a v3 response
    def bars(self, symbol: str, start: int, asof: int) -> pd.DataFrame       # build_symbol(client, symbol, asof, start)[0]
        # raises if the frame is empty or ANY request failed (wrap the client: build_symbol swallows analytics/funding errors)
class Fetched      # dataclass: frames: dict[str, pd.DataFrame], errors: dict[str, str], server_time: pd.Timestamp | None
def closed_asof(now: pd.Timestamp, settle_seconds: int) -> pd.Timestamp      # floor_hour(now - settle_seconds)
def symbols_needed(universe: dict[str, list[str]], start: pd.Timestamp, asof: pd.Timestamp, held: set[str],
                   extra: tuple[str, ...]) -> tuple[list[str], list[str]]    # (required, context)
    # required = PF_XBTUSD, PF_ETHUSD + this month's universe + held (a position or order in any book) + extra
    # context  = in the universe of an earlier month the window touches (cross-sectional strategies need their history)
def fetch(source, symbols: list[str], start: pd.Timestamp, asof: pd.Timestamp, workers: int = 8) -> Fetched
    # source.bars per symbol in a thread pool, one retry per failure; keeps only rows with start <= bar time < asof
def prepare(frames: dict[str, pd.DataFrame], t_last: pd.Timestamp, delist_after_bars: int, model: dict | None = None
            ) -> tuple[dict[str, pd.DataFrame], dict[str, int], dict[str, int]]     # data, gaps, bad
def build_base(data: dict[str, pd.DataFrame], t_cap: pd.Timestamp) -> FeedBase
    # as runner.load_market: make_base(data, store.tradable_mask & ~bar_missing, slip_table(data), end=t_cap + 1h)
# desk/bot/guardian.py: kill switch, feed pre-flight, data checks, halts, alert log
class Alert        # dataclass: level, code, message: str; book: str = "", symbol: str = "", detail: dict | None = None
class Verdict      # dataclass: usable: bool, frozen: bool, t_last: pd.Timestamp | None, age_minutes: float | None, alerts: list[Alert]
def kill_requested(cfg: BotConfig, state_dir: Path) -> bool                  # cfg.kill or state/KILL exists
def preflight(fetched: Fetched, required: list[str], now: pd.Timestamp, asof: pd.Timestamp, cfg: BotConfig,
              prev_feed_time: pd.Timestamp | None) -> Verdict                # step 4 below
def universe_cap(t_last: pd.Timestamp, universe: dict[str, list[str]]) -> pd.Timestamp | None
def check_data(data: dict, gaps: dict, bad: dict, watched: set[str], needs: dict[str, tuple],
               t_last: pd.Timestamp, cfg: BotConfig) -> list[Alert]          # needs = {book: strategy.needs}
def halt(engine: Engine, reason: str, now: pd.Timestamp) -> None             # the engine has no public halt:
    # engine._halt(reason, state.last_time or now.isoformat(), UTC day number of now); if already halted, only raise halt_day
def write_alerts(state_dir: Path, alerts: list[Alert], tick_utc: str) -> None
# desk/bot/paper.py: tick, loop, status, state and log storage, CLI entry point (CONFIG = "config/bot.yaml", STATE = "state")
def tick(config_path=CONFIG, state_dir=STATE, now: pd.Timestamp | None = None, source=None) -> dict   # the heartbeat; never raises
def loop(config_path=CONFIG, state_dir=STATE, source=None, max_ticks: int | None = None) -> None
def status(state_dir=STATE, now: pd.Timestamp | None = None) -> dict           # {"healthy": bool, "why": str, "heartbeat", "books"}
def atomic_write_json(path: Path, obj: dict) -> None                         # temp file, fsync, os.replace
def append_lines(path: Path, lines: list[str]) -> int                        # one write + fsync; returns the new size
def read_log(state_dir: Path, stem: str, since: pd.Timestamp | None = None) -> list[dict]   # "ledger_champion": rotated + live
def retire_book(state_dir: Path, book: str, why: str, tick_utc: str) -> Path   # moves the three logs first, the state file last
# desk/bot/report.py: 24-hour and weekly summaries, promotion check, paper vs backtest (both CLIs: main(argv=None) -> int)
def build_report(state_dir=STATE, hours: int = 24, now=None, results_dir="research/results") -> dict
def promotion(state_dir=STATE, days: int = 7, now=None) -> dict
def render(report: dict) -> str
```
`prepare`, per symbol: (1) a bar whose OHLC is NaN, `<= 0` or has `high < low` becomes a missing bar; (2) rows
after `t_last` are dropped; with `g` = hours from the last real bar to `t_last`, `0 < g < delist_after_bars` appends
`g` missing bars (close forward-filled, open = high = low = close, volume 0, `bar_missing` True, the rest NaN) and
`g >= delist_after_bars` leaves the frame ending at its last real bar; (3) absent columns other than OHLCV become NaN;
(4) `funding_is_est`, `funding` and the float32 casts exactly as in `download.fit_funding`, with `a`, `k` per symbol
(else pooled) from `model`, which is `data/manifest.json -> funding_model` when None. `gaps[s] = g` where `g > 0`;
`bad[s]` = bars rewritten in (1).

## File formats
All times are ISO-8601 UTC. **Bar time is the bar's OPEN time**, as in the research data: bar `01:00` closes
at `02:00`. JSON is written with NaN as `null` (`allow_nan=False`); numpy scalars are converted first.
```text
state/<book>.json  {"schema": 1, "book", "started_bar", "updated_utc", "engine": State.to_json(),
                    "strategy": {"module", "name", "params": {...}, "valid_bars", "max_hold", "equity0"},   # the fingerprint
                    "log_bytes": {"decisions": 0, "ledger": 0, "equity": 0}}                                # committed sizes
decisions line     {"time": bar, "book", "strategy", "event", "symbol", "reason", ...engine fields, "tick_utc"}
ledger line        the engine's trade dict + "book", "strategy", "tick_utc"
equity csv         time,equity,gross,tick_utc             (header row, then one row per processed bar)
alerts line        {"tick_utc", "level": "info|warn|critical", "code", "book", "symbol", "message", "detail"}
heartbeat.json     {"schema": 1, "tick_utc", "ok", "mode": "paper", "killed", "seconds", "error",
                    "feed": {"usable", "frozen", "feed_time", "age_minutes", "symbols", "failed": []},
                    "alerts": {"info": 0, "warn": 0, "critical": 0}, "books": {"champion": {"strategy", "status", "detail",
                    "last_bar", "lag_bars", "equity", "day_pnl", "positions", "orders", "halted", "halt_reason"}, ...}}
```
- Decision events: the engine's (`order_created`, `order_cancelled`, `order_expired`, `order_rejected`,
  `signal_blocked`, `entry`, `exit`, `guardian_halt`) plus the bot's `book_started` and `resume`. `reason` is always
  present: the engine's where it gives one, else `paper.REASONS[event]`.
- Book `status`: `empty` (config null), `waiting` (new, feed not usable yet), `ok` (advanced), `idle` (nothing
  new), `closing`, `error`. `feed_time` is `T_last`; it keeps its previous value while the feed is not usable.

## One tick (`paper.tick`)
`asof = closed_asof(now, settle_seconds)`: bars with open time `< asof` are closed. `T_end = asof - 1h`. `T_last` =
BTC's newest real bar. `T_cap` = newest bar `<= T_last` whose month is in `data/universe.json`. A book's `lag` =
hours from its `last_time` to `T_end` (normally 1; 0 on a repeated tick).
0. **Lock.** Create `state/tick.lock` with `O_CREAT|O_EXCL` (pid, start time); remove it in `finally`. If it exists and
   is under 20 minutes old: print "another tick is running", exit 0, touch nothing. Older: delete it, alert `lock_stale`, go on.
1. **Config.** `load_config`; on `ConfigError`: alert `config_invalid`, heartbeat, exit 1. Then
   `store.universe.cache_clear()` (a `loop` process must see an updated universe file); `kill_requested` (alert `killed`).
2. **Books.** For each book read `state/<book>.json`. No file: a new book if the config names a strategy, else
   `empty`. Unreadable, `schema != 1` or `State.from_json` fails: retire (`unreadable`), alert `state_unreadable`, new
   book. Fingerprint differs from the config, or the config entry is now null: the book is `closing` (step 6c).
   Cut each log that is longer than its `log_bytes` back to that size (alert `log_rollback`); a shorter log is
   accepted as it is. Move `decisions_*` and `alerts` files above 5 MB (`MAX_LOG_MB`) to `state/archive/rotated/`.
3. **Window.** A book with `lag > max_catchup_bars` is retired (`too_old`, alert `state_too_old`) and starts new.
   `start = asof - (window_bars + largest lag) hours`, so every replayed bar has at least `window_bars` bars behind
   it. `required, context = symbols_needed(store.universe(), ...)`.
4. **Fetch and pre-flight.** `fetch`, then `guardian.preflight`. While the feed is not usable no book processes a
   bar; the next usable tick replays what was missed.
   - a required symbol failed or BTC has no bar: not usable, alert `feed_incomplete` (a failed context symbol is
     only left out, with a `context_missing` warning);
   - `|now - server_time| > max_clock_skew_seconds`: not usable, alert `clock_skew`;
   - `T_last < T_end`: alert `feed_late`. Feed age = minutes from `T_last + 1h` to `now` (if not usable: from the
     previous heartbeat's `feed_time`, unknown = not frozen); above `stale_feed_minutes`: `frozen`, alert `feed_frozen`.
5. **Data** (usable only). `prepare`; `T_cap = universe_cap(...)`, alert `universe_stale` if `T_cap < T_last`;
   `build_base`; `check_data` alerts for symbols that are held or in this month's universe.
6. **Each book**, champion first, inside its own `try/except`: an exception raises alert `book_error` with the
   traceback, nothing of that book is written, and the other books still run.
   a. `Engine(Costs(), cfg.risk, valid_bars, max_hold, state, log_events=True)`: `valid_bars` and `max_hold` from
      the book's fingerprint, `halt_sticky=True` in the Risk while killed.
   b. Halts. Killed: `guardian.halt(engine, "manual kill", now)`. Not killed and `halt_reason` is `"manual kill"`:
      `engine.resume()` (decision `resume`). Frozen feed: `guardian.halt(engine, "frozen data feed", now)`.
   c. Closing book: delete its orders, set `exit_pending = "strategy_swap"` on every position and run the next bar
      with blank intents (the engine closes them at that bar's open), commit as in e. Once flat: `retire_book`
      (`swapped`), alert `strategy_changed`, and carry on as a new book if the config names a strategy.
   d. Run (usable only): `i1` = index after `T_cap`, `i0` = index after `last_time`. A new book starts flat with
      `equity0` and `i0 = i1 - 1` (decision `book_started`): it never trades bars from before it existed. If `i0 < i1`:
      `intents = strategy.intents({s: df.copy()}, params)`, `engine.run(attach(base, intents), i0, i1)`; alert
      `missed_bars` when `i1 - i0 > 1`.
   e. Commit, only if a bar was processed or b/c changed the state: append decisions, trades and equity rows, then
      `atomic_write_json` the state file with the new `log_bytes`.
7. **Finish.** Append the tick's alerts, write the heartbeat atomically, print one line per book. An exception
   outside step 6: alert `tick_error` with the traceback, heartbeat `ok: false`; books already committed stay
   committed. Exit 1 if any `critical` alert was raised this tick, else 0.

## Failure modes
| Situation | What the bot does | Logged |
|---|---|---|
| Tick runs twice in one hour | the second finds `lag = 0`: no bar, no log line, heartbeat rewritten | book `idle` |
| Two processes tick at once | the second sees the lock and exits 0 | `lock_stale` warn if an old lock was broken |
| Tick late, hours missed, bot down | every missed bar is replayed in order on a window extended by the lag: same result as hourly ticks | `missed_bars` warn; `state_too_old` critical past `max_catchup_bars` |
| Crash after the logs, before the state | uncommitted log bytes are cut off and the bar is redone | `log_rollback` warn |
| Feed serves a still-open bar (it does), clock skew | `asof` floors the clock minus `settle_seconds`, `fetch` drops rows `>= asof`, and the clock is checked against the venue: beyond the limit nothing is processed | `clock_skew` critical |
| Feed late or frozen | late: wait. Frozen: Guardian halt on every book (orders cancelled, positions closed at the open of the first bar after the freeze began, no entries until the UTC day after the last frozen tick) | `feed_late` warn, `feed_frozen` critical |
| A required symbol cannot be fetched (held or not) | no book advances; replayed next tick; the frozen rule applies if it lasts | `feed_incomplete` warn, then `feed_frozen` |
| Symbol stops printing bars while held | under `delist_after_bars`: missing bars (position kept at its last price, no new entries), the research-data convention. After that the engine closes it as `delisted` and cancels its orders | `bar_missing` warn, `symbol_delisted` warn |
| Bad bar (NaN, `<= 0`, high < low) | treated as a missing bar | `bad_bar` warn |
| Strategy needs columns or symbols the window lacks | the feed always holds BTC, ETH, `extra_symbols` and every symbol in any universe month the window touches; `test_bot_window.py` must pass before a strategy is configured; a `needs` column that is NaN on the newest bar but was present an hour earlier is reported | `inputs_missing` warn |
| New month absent from `data/universe.json` | bars of that month are not processed; books wait and replay them once the file has the month. No carry-forward: strategies read the same file through `store.tradable_mask` | `universe_stale` critical each tick |
| State file corrupt or other schema | retired to `state/archive/`; the book restarts flat with `equity0` | `state_unreadable` critical |
| Strategy raises for one book | that book is skipped (state untouched, replayed later); the others run | `book_error` critical |
| Config changes a book's strategy, params or `equity0` | old book flattened by the engine at the next bar's open and retired; new book starts flat | `strategy_changed` info |
| Logs growing forever | `decisions_*` and `alerts` rotate at 5 MB; ledger and equity are kept whole (about 0.5 MB per book per year) | - |
| `state/KILL` or `kill: true` | sticky halt on every book: orders cancelled, positions closed at the next bar's open, no entries; ticks continue so equity and heartbeat stay current. Removing it resumes at once | `killed` warn each tick |

## Guardian limits (paper mode)
- Per order, inside the engine: a stop must be attached and on the correct side; stop distance between 0.2% and 25%
  of price; position notional capped at 1x equity; gross exposure capped at 3x equity; no entries outside the
  month's universe, on a missing bar, or while halted.
- Account level: -3% on the UTC day or three losing trades in a row cancels all orders, flattens all positions at
  the next bar's open and blocks entries until the next UTC day. (Backtests model the same auto-resume so paper and
  backtest stay comparable. For live trading the halt will be sticky until the owner resumes: `halt_sticky`.)
  Feed-level and manual halts are in the table above.

## Books, swaps and promotion
Champion and each challenger trade in separate books with the same $10,000 notional and the same limits. Only the
champion book is "the bot's trades"; challenger books are shadow P&L. A book's live files always describe one
strategy run since `started_bar`: any change of strategy, params or `equity0` retires the book and starts a fresh
one, so promoting a challenger (by editing `config/bot.yaml`) restarts it flat as champion. `report.promotion` only
flags; a person edits the config. A day is "winning" when the book's last equity of the UTC day is above the
previous day's. A challenger is `ready` when it has at least 7 winning days, its P&L since `started_bar` is
positive, and that P&L beats the champion's over the same days.

## CLI and cloud run
```text
python -m desk.bot.paper tick   [--config config/bot.yaml] [--state state]   exit 0 ok, 1 a critical alert
python -m desk.bot.paper status [--state state] [--json]    exit 1 if no heartbeat, not ok, or older than 2 h
python -m desk.bot.paper loop   [--config ...] [--state ...]    tick, sleep to the next hour + settle_seconds + 30 s, repeat
python -m desk.bot.report       [--state state] [--hours 24] [--json]        --hours 168 = weekly
```
- The report shows: bot health; per book equity, P&L, closed trades with reasons, open positions and halts; alerts
  grouped by code; the promotion check; paper next to `research/results/<strategy>.json`.
- `.github/workflows/paper-bot.yml`: hourly at minute 7 plus manual dispatch, `concurrency: paper-bot` without
  cancel-in-progress, no secrets. Steps: check out the code; check out branch `bot-state` into `state/` (create it
  if absent); install `requirements.txt`; `tick`; then, even if the tick failed, write `state/report.md` and commit
  and push `state/` (never `*.lock` or `*.tmp`). A non-zero tick fails the job, so GitHub notifies the owner.

## Tests (no network: a fake source and `tmp_path`; every test module blocks sockets)
- `test_bot_config.py`, `test_bot_feed.py` (`closed_asof`, `symbols_needed`, `prepare`), `test_bot_report.py`,
  `test_bot_paper_only.py` (no order or credential strings in `desk/bot`, GET only).
- `test_bot_tick.py`: hourly ticks equal one `Engine.run` over the same bars (trades and equity); repeated tick;
  missed ticks; crash before the state write; corrupt state; lock; kill and resume; frozen feed; failing strategy;
  strategy swap; null champion; month without universe; failed symbol.
- `test_bot_window.py`: strategies see `window_bars` of history, not four years. For every configured strategy the
  last 200 intents on (window, bot symbol set) must equal those on (full history, all symbols): same `side`/`exit`,
  prices within 1e-9 relative; if not, raise `window_bars`. Verified 2026-11-18 against the live API: a 3000-bar
  frame from `build_symbol` plus `prepare` equals the research rows in every column; the slippage table and
  `ref_donchian` intents are identical on the last 2000 bars (13 symbols, 17 requests each).

## Not built yet (deliberately)
- A live broker adapter. `mode: live` is refused. It will be written and tested with minimum size only
  after the owner says "go live", with a trade-only API key that cannot withdraw, held in a secret store.
- The monthly universe refresh. Until it exists someone runs `python -m desk.data.download` on the 1st and commits
  `data/universe.json`; the bot waits and alerts until then (`docs/RUNBOOK.md`).
- Known paper-vs-live gap: a market order fills at the next bar's open although the tick runs minutes after that
  open. The audit's `one_bar_late` stress test bounds the effect.
