"""Why does trend_quiet_grind give no entry signal on the live 5000-bar window? Is it the market (no smooth
14-day rise lately) or the data (a hole that keeps the 4320-bar rank empty)? Read-only GETs, no account.
    PYTHONPATH=. python research/builder/probe_quiet_grind_live.py [window_bars]"""
import sys

import pandas as pd

from desk.bot import feed as F
from desk.data import store
from desk.strategies import ta
from desk.strategies.s_trend_quiet_grind import STRATEGY as S

HOUR = pd.Timedelta(hours=1)
wb = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
asof = F.closed_asof(pd.Timestamp.now(tz="UTC"), 120)
start = asof - (wb + 1) * HOUR
required, context = F.symbols_needed(store.universe(), start, asof, set(), ())
got = F.fetch(F.KrakenSource(), required + context, start, asof)
data, gaps, bad = F.prepare(got.frames, asof - HOUR, 72)
print(f"window {wb}: {len(data)} symbols, failed {got.errors or 'none'}, gaps {gaps or 'none'}, bad {bad or 'none'}")
p = dict(S.params)
it = S.intents({s: d.copy() for s, d in data.items()}, p)
for s, df in sorted(data.items()):
    c = df["close"]
    er = ta.efficiency_ratio(c, p["L"])
    rk = ta.rolling_rank(er, 4320)
    up = ta.ret(c, p["L"]) > 0
    print(f"  {s:<14} bars {len(df):>5} missing {int(df['bar_missing'].sum()):>3}  er NaN {int(er.isna().sum()):>4}  "
          f"rank known on {int(rk.notna().sum()):>4} bars, max {rk.max():.2f}, >= q on {int((rk >= p['q']).sum()):>3}, "
          f"of which 14-day return > 0: {int(((rk >= p['q']) & up).sum()):>3}  signals {int((it[s]['side'] != 0).sum())}")
