"""Right after an hour closes: is the bar that just closed complete on the live API, for every symbol the bot
needs, with all its columns? Run it at hh:02:30 (when `loop` ticks) and at hh:07 (when GitHub ticks).
Read-only GET requests, no account.     PYTHONPATH=. python research/builder/probe_newest_bar.py"""
import pandas as pd

from desk.bot import feed as F
from desk.data import store

HOUR = pd.Timedelta(hours=1)
now = pd.Timestamp.now(tz="UTC")
asof = F.closed_asof(now, 120)
newest = asof - HOUR
required, _ = F.symbols_needed(store.universe(), asof - 12 * HOUR, asof, set(), ())
src = F.KrakenSource()
got = F.fetch(src, required, asof - 12 * HOUR, asof)
print(f"now {now:%H:%M:%S} UTC, venue clock {got.server_time}, newest closed bar {newest:%Y-%m-%d %H:%M}, "
      f"{len(got.frames)}/{len(required)} symbols, failed {got.errors or 'none'}")
late, holes = [], {}
for s, df in sorted(got.frames.items()):
    if df.index[-1] < newest:
        late.append(f"{s} (newest {df.index[-1]:%H:%M})")
        continue
    row = df.loc[newest]
    empty = [c for c in df.columns if c != "bar_missing" and pd.isna(row[c])]
    if empty:
        holes[s] = empty
print("symbols whose newest bar is not served yet:", late or "none")
print("columns still empty on the newest bar:", holes or "none")
