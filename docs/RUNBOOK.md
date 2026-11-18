# Paper bot runbook

**Paper trading only.** The bot reads public prices from Kraken Futures and simulates trades with pretend
money. It cannot place a real order, it holds no login for any exchange, and the code refuses any setting
other than `mode: paper`. Design and file formats: `docs/BOT_SPEC.md`; where the code has moved on since
that document was written, the list at the top of `desk/bot/paper.py` says how.

## The short version
| I want to | Do this |
|---|---|
| See how it is doing | Open `report.md` on the `bot-state` branch (rewritten every hour) |
| Know if it is alive | `python -m desk.bot.paper status` prints HEALTHY or NOT HEALTHY, why, and what is trading |
| Stop everything | Put a file named `KILL` next to the bot's files (see "Pausing the bot") |
| Start again | Delete `KILL` (and make sure `kill: false` in `config/bot.yaml`) |
| Choose or change the strategy | Edit `champion:` in `config/bot.yaml` and commit |
| Try a strategy on the side | Add it under `challengers:` (at most two) |
| Understand a red (failed) run | Find its code in "Alerts and what to do" |

## Starting it the first time
1. Get `.github/workflows/paper-bot.yml` onto the default branch (`main`). Until then nothing runs.
2. On the Actions tab choose "paper-bot" and press "Run workflow" (or wait for minute 7 of the next hour).
   The first run creates the branch `bot-state` and puts `heartbeat.json` and `report.md` on it. It takes
   about two minutes and should be green.
3. As shipped, `config/bot.yaml` says `champion: null`: the bot wakes every hour, checks the price feed and
   trades nothing. `report.md` then reads `HEALTHY` and `Trading: nothing: no champion strategy is configured`.
   That is the expected state until a champion is chosen.
4. When the champion is chosen, follow "config/bot.yaml: champion and challengers" below. The run after the
   change shows the champion book with $10,000.00 and "new book" among its decisions. A first trade can take
   hours or days, depending on the strategy.

## What the bot does each hour
One run is called a **tick**. It handles the hour that has just closed. In order:
1. **Reads `config/bot.yaml`** and checks whether the kill switch is on.
2. **Loads each book** (the champion's account and up to two challengers' shadow accounts). If an earlier
   run died half way, its unfinished lines are removed so nothing is ever recorded twice.
3. **Checks its own clock against Kraken's.** If they disagree by more than 30 seconds, or Kraken's clock
   cannot be read, nothing is processed and no book is touched.
4. **Fetches the last 125 days of hourly prices** for BTC, ETH, this month's ten tradable coins and anything a
   book holds. Only finished hours are used. If something needed is missing, the bot waits; the hour is
   processed later with exactly the result it would have had on time.
5. **Checks the prices.** Impossible bars (zero, negative, not a number, high below low) and bars printed far
   away from Kraken's own mark and index prices are treated as "no bar" and reported.
6. **For each book:** the strategy decides, the Guardian checks every order (a stop must be attached, size
   and total exposure are capped, only this month's ten coins), and the same simulator the backtests use
   fills orders against the real bar, with fees, slippage and funding. Every decision is written down with
   its reason.
7. **Saves everything** and writes the heartbeat. If anything critical happened the run ends as "failed" so
   that GitHub notifies you.

If runs were missed (GitHub skipped an hour, the machine was off), the next run processes every missed hour
in order. The result is the same as if it had run every hour.

## Where to look
In the cloud the bot's files live on the branch **`bot-state`** (created by the first run), not on `main`.
On your own machine they are in the folder `state/`.

| File | What it is | When to open it |
|---|---|---|
| `report.md` | the last 24 hours in plain words: health, what is trading, each book's result, trades, alerts, the promotion check | daily |
| `heartbeat.json` | result of the last run: `ok`, the time, the price feed, one entry per book | "is it alive?" |
| `alerts.jsonl` | everything the Guardian flagged, one line each, with a code and a message | after a red run |
| `ledger_<book>.jsonl` | every closed trade with its profit or loss and why it was closed | to check trades |
| `decisions_<book>.jsonl` | every decision with its reason: signal, order, fill, exit, block, halt | "why did it do that?" |
| `equity_<book>.csv` | account value after every hour | for a chart |
| `champion.json`, `challenger_1.json`, `challenger_2.json` | each book's account right now: cash, positions, orders | rarely |
| `archive/` | books that were retired (strategy changed, damaged file) and old log files | rarely |

`<book>` is `champion`, `challenger_1` or `challenger_2`. Only the champion is "the bot's trades"; the
challengers are shadow accounts for comparison.

Commands (run from the repository folder):
```bash
python -m desk.bot.paper status               # HEALTHY / NOT HEALTHY, why, what is trading
python -m desk.bot.report --hours 24          # the daily report (168 = weekly)
```
`status` says NOT HEALTHY when the last run raised something critical, when the last run is more than two
hours old, or when the bot has never yet received usable prices. HEALTHY does not mean "trading": read the
`Trading:` line under it (for example `nothing: no champion strategy is configured`, or
`champion ... is HALTED by the Guardian`).

## Pausing the bot (the kill switch)
- **On:** create a file named `KILL` next to the bot's files. In the cloud: open the `bot-state` branch on the
  GitHub website, "Add file" -> "Create new file", name it `KILL`, type any word in it, commit. On your own
  machine: create `state/KILL`. The name may be in any letter case and may end in `.txt`.
  The other way is `kill: true` in `config/bot.yaml`; the file is safer because a typo in the config stops
  the config from loading at all.
- **What happens on the next run:** every waiting order is cancelled, every position is sold at the opening
  price of the hour being processed, and nothing new is opened. Runs continue, so the report stays current.
  Each run writes the alert `killed` as a reminder.
- **Off:** delete the file and make sure the config says `kill: false`. Trading resumes on the next run.
- The switch acts on the next hourly run, not instantly. To act sooner press "Run workflow" on the Actions tab.
- If the config file is broken at the same time, nothing trades at all (the run fails with `config_invalid`);
  the kill takes effect on the first run after the config is fixed.
- Releasing the switch also clears any Guardian halt the book was under and restarts its loss count for
  the day (alert `resumed`). Do not use it as a routine way round a loss halt.

## config/bot.yaml: champion and challengers
```yaml
mode: paper                     # nothing else is accepted
kill: false
champion: {strategy: desk.strategies.s_name, params: {n: 96}}    # params are optional
challengers:
  - {strategy: desk.strategies.s_other}
  - {strategy: desk.strategies.s_third, params: {n: 48}}
```
- `champion: null` (as shipped) means the bot runs, checks the feed and trades nothing.
- **Before** naming a strategy, add it to the config locally and run
  `python -m pytest tests/test_bot_window.py -q` (needs the research data, `python -m desk.data.download`).
  It checks that the strategy decides the same on the bot's 125 days of history as on the full history. If it
  fails, raise `feed.window_bars` until it passes, or do not use that strategy.
- **`trend_quiet_grind` needs a longer window.** Checked on 2026-11-18 for all 18 strategies in
  `desk/strategies` (`PYTHONPATH=.:tests python research/builder/probe_window_all.py 3000 5000`): 17 decide
  the same on the default 3000 hours as on the full history. `trend_quiet_grind` does not: it compares a
  value with its own last 4320 hours, so on 3000 hours it would **never signal, without any error**. If it is
  used in any book, the config must also say
  ```yaml
  feed: {window_bars: 5000}
  ```
  (verified: same decisions as on the full history, and a live run then takes about 22 seconds instead of
  12). A strategy added later must be checked the same way. When a book starts and its strategy shows no
  signal anywhere in its history, the bot warns with `strategy_silent`; in a falling market this strategy
  can raise that warning even with the right window, because only its last two weeks can signal.
- Commit the change. The next run starts the book flat with $10,000 of paper money. It never trades hours
  from before it existed.
- **Changing a book's strategy, its params or `equity0` ends that book**: its positions are sold at the next
  bar's open, its files move to `archive/`, and a fresh book starts flat (alert `strategy_changed`). A
  book's files therefore always describe one strategy.
- **Challengers keep their place.** A challenger's record stays with it when you reorder the list, remove the
  other challenger or promote the other one. It may keep showing under its old name (`challenger_2`) even
  if it is now first in the list; that is harmless.
- **Promotion.** `report.md` ends with a promotion check: a challenger is READY after at least 7 winning
  days, a positive result since it started, and a better result than the champion over the same days.
  Nothing happens automatically. To promote, move the challenger's entry to `champion:`. The old champion
  book is closed and archived, the promoted strategy starts a new champion book flat (its shadow record
  stays in `archive/`), and the other challenger carries on untouched.
- The limits under `guardian:`, `risk_per_trade`, `stale_feed_minutes` and `max_clock_skew_seconds` may be
  made stricter, never looser. Changing a limit does not restart a book.
- A typo, an unknown setting, an unknown strategy or parameter, `mode` other than `paper`, or any setting
  that looks like a login makes the run fail with `config_invalid`; nothing trades until it is fixed.

## What the Guardian does by itself
| Trigger | Action | When it lifts |
|---|---|---|
| A book is down 3% on the day (UTC) | cancel its orders, sell everything at the next bar, no entries | next UTC day |
| Three losing trades in a row | same | next UTC day |
| No usable prices for more than 90 minutes while the bot was running | same, on every book | the UTC day after prices return |
| Kill switch | same, on every book | when you release it |
| An order without a valid stop, too large, or outside this month's ten coins | that order is refused | - |
| A held coin stops trading or Kraken stops answering for it for 72 hours | that position is closed at its last price | - |

"While the bot was running" matters: one failed download is never a frozen feed by itself, however late
GitHub started that run and however long the bot had not been started before. A later run confirms it: if
a run at least 20 minutes after the first failure fails too and the prices are by then more than 90 minutes
old, the feed is frozen.

## Alerts and what to do
A run is marked failed (red) when it raised a `critical` alert. `warn` and `info` never fail a run.

| Code | Level | Meaning | What to do |
|---|---|---|---|
| `guardian_halt` | critical for the champion, warn for a challenger | the Guardian stopped a book for the day: -3% or three losses in a row. Its positions are sold at the next bar | nothing; it lifts at the next UTC midnight. The red run is the notification, not a malfunction. Read the trades in `report.md` |
| `feed_frozen` | critical | no usable prices for more than 90 minutes; every book is halted and sold at the next available bar | check status.kraken.com. The bot recovers by itself; entries return the UTC day after. If it happens on the very first runs, the bot has never reached Kraken: read the `feed_incomplete` line before it |
| `feed_incomplete` | warn | a needed coin, or Kraken's clock, could not be fetched this run; no book advanced | nothing unless it repeats; an hour later it becomes `feed_frozen` |
| `feed_late` | warn | the newest hour is not published yet, for BTC or for a coin the bot holds; the bot waits one run | nothing |
| `context_missing` | warn | a coin used only for history could not be fetched | nothing unless it repeats for days |
| `clock_skew` | critical | this machine's clock disagrees with Kraken's; nothing was processed, no book was touched | rare in the cloud; on your own machine switch on automatic time setting |
| `universe_stale` | critical | new month, `data/universe.json` not refreshed; the new month is not traded | do the monthly refresh below; the waiting hours are then processed |
| `killed` | warn | the kill switch is on | delete `KILL` to resume |
| `resumed` | info | the kill switch was released; the book may trade again and its halt, if any, was cleared | nothing |
| `missed_bars` | warn | several hours were processed in one run | nothing |
| `bar_missing` | warn | a coin printed no bar for an hour; its position is kept at the last price, no new entries in it | nothing |
| `bad_bar` | warn | a bar with impossible or off-market prices was ignored (repeats while the bar is within the 125 days) | nothing; if it names a coin you hold every hour, look at that coin on Kraken |
| `symbol_delisted` | warn | a coin printed no bar, or could not be fetched, for 72 hours; positions in it were closed, its orders cancelled | nothing; if the coin is still trading on Kraken, tell a maintainer |
| `inputs_missing` | warn | a data column a strategy needs went empty | watch; while it lasts that strategy cannot signal on that coin |
| `log_rollback` | warn | an earlier run died midway; its half-written lines were removed and the hour redone | nothing |
| `lock_stale` | warn | an earlier run died and left its lock | nothing |
| `strategy_silent` | warn | raised once, when a book starts: its strategy has not one entry signal in all the history the bot holds. Either the market gave it no setup lately, or it needs more history than `feed.window_bars` and will never trade | make sure the window check (under "config/bot.yaml" above) passes for that strategy. If it passes, nothing: the book trades when a setup comes. If it fails, raise `feed.window_bars` |
| `strategy_changed` | info | a book was closed and archived after a config change | nothing |
| `book_error` | critical | a strategy crashed; that book skipped the hour (it is redone later), the others ran. With the kill switch on or a frozen feed the book is still flattened | send the alert's `detail` to whoever maintains the strategy; set that book to another strategy or `null` meanwhile |
| `state_unreadable` | critical | a book's file was damaged; it was archived and the book restarted flat | look in `archive/`; ask a maintainer how the file got damaged |
| `state_too_old` | critical | the bot was down longer than 2000 hours; the book was archived and restarted flat | nothing |
| `config_invalid` | critical | `config/bot.yaml` has an error; nothing ran | fix the config (the message says what is wrong) |
| `tick_error` | critical | anything else went wrong; the run is retried next hour | if it repeats, send `detail` to a maintainer |

## Running in the cloud (GitHub Actions)
- `.github/workflows/paper-bot.yml` wakes the bot every hour at minute 7 and has a "Run workflow" button.
  **It only takes effect once that file is on the repository's default branch** (normally `main`); GitHub
  ignores schedules on other branches.
- It uses no passwords or keys of any kind. It needs permission to save the bot's files: if the first run
  fails with a "permission denied" message while pushing, set Settings -> Actions -> General -> Workflow
  permissions to "Read and write permissions".
- GitHub sometimes starts a few minutes late or skips an hour. The bot catches up on its next run.
- If a run fails, GitHub marks it red and emails the person who last edited the workflow file (check
  Settings -> Notifications -> Actions on your GitHub account). The run's log and `alerts.jsonl` say why.
- GitHub switches scheduled workflows off after 60 days without activity in the repository. If the runs
  stop, open the Actions tab and re-enable the workflow. `status` then says the last tick is hours old.

## Running on an always-on machine instead
Use this or GitHub for a given set of files, never both: two bots writing the same files would each treat
the other's work as a repeated run. Stop the GitHub schedule first (Actions tab -> paper-bot -> "Disable
workflow") and copy the files from the `bot-state` branch into `state/` if you want to keep the history.

```bash
pip install -r requirements.txt
python -m desk.bot.paper tick       # one run now; exit code 1 if something critical happened
python -m desk.bot.paper loop       # run now, then two and a half minutes after every full hour, forever
```
`loop` must be kept alive by a supervisor that restarts it if it ever stops. Nothing is lost by a restart:
the next run redoes the unfinished hour. On Linux, create `/etc/systemd/system/paper-bot.service`
(replace the two paths and the user name):
```ini
[Unit]
Description=Paper trading bot (paper only)
After=network-online.target
Wants=network-online.target

[Service]
User=desk
WorkingDirectory=/home/desk/TRAYDINGCc
ExecStart=/usr/bin/python3 -m desk.bot.paper loop
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```
then `sudo systemctl enable --now paper-bot` (start, and start again after every reboot),
`systemctl status paper-bot` (is it running), `journalctl -u paper-bot -n 50` (its last lines). Without
systemd, this restart loop in a terminal that stays open does the same job:
```bash
while true; do python -m desk.bot.paper loop; sleep 60; done
```
On your own machine:
- The clock must be right (automatic time setting on); otherwise every run reports `clock_skew`.
- Nobody emails you. Check `python -m desk.bot.paper status` daily, or schedule it: it exits with code 1
  when the bot is not healthy or has not run for two hours.
- The report is not written by itself: `python -m desk.bot.report > state/report.md`.
- If the process is killed hard, it leaves `state/tick.lock`. Runs skip for up to 20 minutes ("another tick
  is running"), then the lock is removed with a `lock_stale` warning and the missed hour is processed.
- `git pull` on the 1st of the month brings the new `data/universe.json` (see below); `loop` picks it up
  without a restart.

## Monthly refresh (1st of each month, UTC)
The ten tradable coins are fixed per month in `data/universe.json`. The file must be extended on the 1st;
until then the bot processes nothing from the new month and raises `universe_stale` every hour. Nothing is
lost: once the file is committed the bot processes the hours it waited.
```bash
python -m desk.data.download        # about 5 minutes, public data
git add data/universe.json data/manifest.json data/symbols_seen.json
git commit -m "Universe for the new month" && git push
```

## If something looks wrong
- **NOT HEALTHY, last tick hours ago**: the runs stopped. Actions tab -> is the workflow enabled, are runs
  red? Open the newest run's log; the last lines name the problem. On your own machine:
  `systemctl status paper-bot`.
- **NOT HEALTHY, "never had usable market data"**: the bot has not yet managed one complete download. The
  `feed_incomplete` alert names what failed.
- **A book shows HALTED**: see the Guardian table for when it lifts. A loss halt lifts by itself at the next
  UTC midnight.
- **HEALTHY but `Trading: nothing`**: no champion is configured, or the kill switch is on.
- **Start a book from scratch**: change nothing in the config; move `<book>.json`,
  `decisions_<book>.jsonl`, `ledger_<book>.jsonl` and `equity_<book>.csv` into a folder under `archive/`.
- **Tests** (no network, about three minutes): `python -m pytest tests/test_engine.py tests/test_bot_*.py -q`

## Deliberately not built
- **Live trading.** `mode: live` is refused by the code, there is no broker connection in the repository
  and no place to put an API key. It will be written and tested with minimum size only after the owner says
  "go live", with a trade-only key that cannot withdraw, kept in a secret store.
- **The automatic monthly refresh** (manual steps above).
- **Notifications of its own.** The only push message is GitHub's email about a failed run.
- Known differences from live trading: a simulated market order fills at the bar's opening price although the
  run happens minutes later (the audit's "one bar late" test bounds the effect); the kill switch and the
  Guardian act once an hour, not within seconds.
