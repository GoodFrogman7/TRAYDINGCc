# Paper bot runbook

**Paper trading only.** The bot reads public prices and simulates trades. It cannot place a real order and
holds no login for any exchange. Design and file formats: `docs/BOT_SPEC.md`.

## The short version
| I want to | Do this |
|---|---|
| See how it is doing | Open `report.md` on the `bot-state` branch (rewritten every hour) |
| Know if it is alive | `python -m desk.bot.paper status` says HEALTHY or NOT HEALTHY and why |
| Stop everything now | Set `kill: true` in `config/bot.yaml` and commit (or add a file named `KILL` to the `bot-state` branch) |
| Start again | Set `kill: false` (and delete `KILL` if you created it) |
| Choose or change the strategy | Edit `champion:` in `config/bot.yaml` and commit |
| Try a strategy on the side | Add it under `challengers:` (at most two) |

## How it runs
- GitHub wakes the bot every hour at minute 7 (`.github/workflows/paper-bot.yml`). GitHub sometimes starts a
  few minutes late or skips an hour; the bot then processes the missed hours on its next run, with the same
  result as if it had run on time.
- One run ("tick") handles the hour that just closed: it fetches prices, lets each strategy decide, simulates
  fills against the real bar, and saves everything.
- The bot's files live on the branch **`bot-state`** (created by the first run), not on `main`:

| File | What it is |
|---|---|
| `report.md` | the last 24 hours in plain words |
| `heartbeat.json` | result of the last run |
| `champion.json`, `challenger_1.json`, `challenger_2.json` | each book's account: cash, positions, orders |
| `decisions_<book>.jsonl` | every decision with its reason (signal, order, fill, exit, block) |
| `ledger_<book>.jsonl` | every closed trade with its profit or loss |
| `equity_<book>.csv` | account value after every hour |
| `alerts.jsonl` | everything the Guardian flagged |
| `archive/` | books that were retired (strategy changed, damaged file) and old log files |

- If a run fails, GitHub marks it red and emails the person who last edited the workflow file (check
  Settings -> Notifications -> Actions on your GitHub account). A red run has a `critical` line in
  `alerts.jsonl` and in the run's log saying what happened.
- GitHub can switch scheduled workflows off after 60 days without activity in the repository. If the runs
  stop, open the Actions tab and re-enable the workflow.

## First start
1. The shipped config has `champion: null`: the bot runs, checks the price feed and stays flat. Let it run a
   few hours and check `report.md` says HEALTHY.
2. Pick the champion. **Before** writing it into the config, run (needs the research data,
   `python -m desk.data.download`):
   `python -m pytest tests/test_bot_window.py -q`
   after adding the strategy to `config/bot.yaml` locally. It checks that the strategy decides the same on
   the bot's 125 days of history as on the full history. If it fails, raise `feed.window_bars` until it passes
   or do not use that strategy.
3. Commit the config. The next run starts the book flat with $10,000 of paper money.

## config/bot.yaml
```yaml
mode: paper                     # nothing else is accepted
kill: false
champion: {strategy: desk.strategies.s_name, params: {n: 96}}    # params are optional
challengers:
  - {strategy: desk.strategies.s_other}
```
- A typo, an unknown setting, an unknown strategy or parameter, `mode` other than `paper`, or any setting that
  looks like a login or key makes the run fail with `config_invalid` and nothing is traded until it is fixed.
- The limits under `guardian:` and `risk_per_trade` may be made stricter, never looser.
- **Changing a book's strategy, its params or `equity0` ends that book**: its positions are sold at the next
  bar's open, its files move to `archive/`, and a fresh book starts flat. This is deliberate: a book's files
  always describe one strategy.
- Changing a Guardian limit does not restart a book.

## Kill switch
- On: set `kill: true` in the config and commit, or put a file named `KILL` (any content) next to the bot's
  files (in the cloud: add it to the `bot-state` branch through the GitHub website). On the next run every
  open order is cancelled, every position is sold at the next bar's open, and no new trade is opened. Runs
  continue so the report stays current.
- Off: set `kill: false` and delete the file. Trading resumes on the next run. Both must be off.
- The switch acts on the next hourly run, not instantly. To act sooner press "Run workflow" on the Actions tab.

## What the Guardian does by itself
| Trigger | Action | When it lifts |
|---|---|---|
| Book down 3% on the day (UTC) | cancel orders, sell everything at the next bar, no entries | next UTC day |
| Three losing trades in a row | same | next UTC day |
| No fresh prices for 90 minutes | same, on every book | the UTC day after prices return |
| Kill switch | same, on every book | when you release it |
| An order without a valid stop, too large, or outside this month's top 10 | that order is refused | - |

## Alerts and what to do
| Code | Level | Meaning | Action |
|---|---|---|---|
| `killed` | warn | the kill switch is on | none; remove `KILL` to resume |
| `feed_late` | warn | newest price bar not published yet | none; the bot waits |
| `feed_incomplete` | warn | a needed symbol (or the venue clock) could not be fetched | none unless it repeats; then see `feed_frozen` |
| `context_missing` | warn | a symbol used only for history could not be fetched | none unless it repeats for days |
| `feed_frozen` | critical | no usable prices for 90 minutes; books halted | check status.kraken.com; the bot recovers by itself |
| `clock_skew` | critical | the machine's clock disagrees with the venue's | rare in the cloud; on your own machine fix the clock |
| `universe_stale` | critical | new month, `data/universe.json` not refreshed | do the monthly refresh below |
| `missed_bars` | warn | several hours processed in one run | none |
| `bar_missing`, `bad_bar` | warn | a symbol printed no bar / a nonsense bar | none |
| `symbol_delisted` | warn | a symbol has been silent for 72 hours; positions in it were closed | none |
| `inputs_missing` | warn | a data column a strategy needs went empty | watch; if it lasts, the strategy cannot signal |
| `log_rollback` | warn | an earlier run died midway; its half-written lines were removed and the hour redone | none |
| `lock_stale` | warn | an earlier run died and left its lock | none |
| `strategy_changed` | info | a book was closed and archived after a config change | none |
| `book_error` | critical | a strategy crashed; that book skipped the hour, others ran | send the alert's `detail` to whoever maintains the strategy |
| `state_unreadable` | critical | a book's file was damaged; it was archived and the book restarted flat | look in `archive/` |
| `state_too_old` | critical | the bot was down longer than 2000 hours; book archived, restarted flat | none |
| `config_invalid` | critical | `config/bot.yaml` has an error; nothing ran | fix the config (the message says what) |
| `tick_error` | critical | anything else went wrong; the run is retried next hour | if it repeats, send `detail` to a maintainer |

## Monthly refresh (1st of each month, UTC)
The tradable top 10 is fixed per month in `data/universe.json`. The file must be extended on the 1st; until
then the bot processes nothing from the new month and raises `universe_stale` every hour. Nothing is lost:
once the file is committed the bot replays the hours it waited.
```bash
python -m desk.data.download        # about 5 minutes, public data
git add data/universe.json data/manifest.json data/symbols_seen.json
git commit -m "Universe for the new month" && git push
```

## Promotion of a challenger
`report.md` ends with a promotion check. A challenger is marked READY after at least 7 winning days, a
positive result since it started, and a better result than the champion over the same days. Nothing happens
automatically. To promote: move the challenger's entry to `champion:` in the config. Both books restart flat
(see above), so the new champion's record starts from zero.

## Running it yourself
```bash
pip install -r requirements.txt
python -m desk.bot.paper tick                 # one run now; exit code 1 if something critical happened
python -m desk.bot.paper status
python -m desk.bot.report --hours 168         # weekly report
python -m desk.bot.paper loop                 # an always-on machine instead of GitHub: runs every hour
```
Use either GitHub or your own machine for a given set of files, not both: two bots writing the same files
would each see the other's work as a repeated run.

## If something looks wrong
- **Report says NOT HEALTHY, last tick hours ago**: the runs stopped. Actions tab -> is the workflow enabled,
  are runs red? Open the newest run's log; the last lines name the problem.
- **A book shows HALTED**: see the Guardian table above for when it lifts. A daily-loss or losing-streak halt
  lifts by itself at the next UTC midnight. To lift a halt earlier, switch the kill switch on for one run and
  off again: releasing the switch clears whatever halt the book was under.
- **Start a book from scratch**: change nothing in the config; move `<book>.json`, `decisions_<book>.jsonl`,
  `ledger_<book>.jsonl` and `equity_<book>.csv` into a folder under `archive/` on the `bot-state` branch.
- **Tests** (no network, about two minutes): `python -m pytest tests/test_engine.py tests/test_bot_*.py -q`

## Not built yet
- Real trading. `mode: live` is refused by the code; there is no broker connection in the repository.
- The automatic monthly refresh (manual steps above).
- Known difference to live trading: a simulated market order fills at the bar's opening price although the run
  happens minutes later. The audit's "one bar late" test bounds the effect.
