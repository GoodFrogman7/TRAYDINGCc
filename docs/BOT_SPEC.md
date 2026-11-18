# Paper bot: spec and architecture

Status: **paper trading only**. No code path in this repo can place a real order.

## What it must do (from the desk owner's brief)
1. Trade the champion strategy on paper, nonstop, on live Kraken Futures prices.
2. Send limit orders with a stop attached (simulated against the next real bars).
3. Record every decision with its reason.
4. Recover by itself after any crash.
5. Swap strategies through one config file.
6. Guardian: check every order before it is placed; kill everything at -3% on the day, three losses in a
   row, or a frozen data feed.
7. Keep two challengers on standby (shadow books) so a challenger can replace the champion after 7 winning
   paper days.

## Constraints that shaped the design
- The cloud can only wake the bot about once an hour, so the bot is a **stateless hourly tick**, not a
  long-running process. One tick = one closed 1-hour bar. A loop mode exists for an always-on machine.
- Backtest and paper results must be comparable, so the tick drives the **same `desk.engine.core.Engine`**
  the backtests use, one new bar at a time, with the state saved to disk between ticks. The engine test
  `test_state_round_trips_through_json_and_resumes_identically` pins this.
- A crash must never corrupt the book: state is written to a temp file and renamed only after the bar has
  been fully processed, so a crashed tick is simply redone by the next one.

## Files
| File | Role |
|---|---|
| `config/bot.yaml` | the one config file: mode, account, champion, challengers, Guardian limits |
| `desk/bot/config.py` | load and validate the config; refuses `mode: live` |
| `desk/bot/feed.py` | fetch the last N closed hourly bars per symbol from Kraken's public API, in the research dataset's column layout (reuses `desk.data.download.build_symbol`) |
| `desk/bot/guardian.py` | pre-flight checks: kill file, frozen/stale feed, bad bars, missed-bar gap, universe freshness; alert log |
| `desk/bot/paper.py` | `tick()` for one hour, `loop()` for an always-on host, `status()`; CLI entry point |
| `desk/bot/report.py` | 24-hour and weekly summaries for the morning brief (trades, P&L, alerts, paper vs backtest) |
| `state/<book>.json` | engine state per book (champion, challenger_1, challenger_2) |
| `state/ledger_<book>.jsonl` | closed trades, append-only |
| `state/decisions_<book>.jsonl` | every decision and its reason, append-only (order created / blocked / filled / expired / exit / halt) |
| `state/equity_<book>.csv` | hourly equity |
| `state/alerts.jsonl` | Guardian alerts, append-only |
| `state/heartbeat.json` | last tick time, last bar processed, per-book equity and halt status |
| `state/KILL` | if this file exists the bot does nothing (manual kill switch) |

## One tick
1. Load config. If `state/KILL` exists: write a heartbeat saying so and stop.
2. Work out the symbols needed: this month's universe, BTC, plus any symbol with an open position or order.
3. Fetch the last `window_bars` closed hourly bars for each (in parallel, with retries).
4. Guardian pre-flight on the feed:
   - newest closed bar must be the hour that just ended; if the feed is older than `stale_feed_minutes`,
     raise a `frozen data feed` alert and do not trade this tick (books are halted until the feed is back);
   - reject symbols whose last bar is missing, NaN or non-positive (alert, skip that symbol's signals);
   - if a book is more than `max_catchup_bars` behind, alert and catch up only that many (documented).
5. For each book: compute the strategy's intents on the window, attach them to the bars, and run the
   engine over the bars newer than the book's `last_time`. Normally that is exactly one bar.
6. Append the engine's events to the decisions log (each with its reason), closed trades to the ledger,
   equity to the equity file; then atomically replace the state file.
7. Write the heartbeat. Any exception anywhere is caught, written to `alerts.jsonl` with the traceback, and
   the tick exits non-zero **without** having replaced any state.

## Guardian limits (paper mode)
- Per order, inside the engine: a stop must be attached and on the correct side; stop distance between 0.2%
  and 25% of price; position notional capped at 1x equity; gross exposure capped at 3x equity; no entries
  outside the month's universe; no entries while halted.
- Account level: -3% on the UTC day or three losing trades in a row cancels all orders, flattens all
  positions at the next bar's open and blocks entries until the next UTC day. (Backtests model the same
  auto-resume so paper and backtest stay comparable. For live trading the halt will be sticky until the
  owner resumes; `halt_sticky` exists for that.)
- Feed level: frozen or stale feed, missing bars, a stale universe file.

## Books
Champion and each challenger trade in separate books with the same $10,000 notional and the same limits.
Only the champion book is "the bot's trades". Challenger books are shadow P&L used for the promotion rule
(a challenger replaces the champion after 7 winning paper days, checked by `report.py`, applied by
editing `config/bot.yaml`). A book whose config entry is `null` stays flat.

## Windowing
Strategies are causal, but indicators with long memory (EMAs) differ slightly when computed on a short
window. `window_bars` defaults to 3000 (125 days). A test compares the last 200 intents computed on the
window with those computed on the full history for every configured strategy and fails if any differ.

## Not built yet (deliberately)
- A live broker adapter. `mode: live` is refused. It will be written and tested with minimum size only
  after the owner says "go live", with a trade-only API key that cannot withdraw, held in a secret store.
