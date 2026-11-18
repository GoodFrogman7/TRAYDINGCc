"""Scratch probe (manual, network): what the public API serves around the newest hourly bar.
Run from the repo root: PYTHONPATH=. python research/builder/probe_feed.py"""
import time

import pandas as pd

from desk.data.download import ANALYTICS, build_symbol
from desk.data.kraken import KrakenFutures

k = KrakenFutures(timeout=15, max_retries=3)
now = int(time.time())
asof = now // 3600 * 3600
print("now", pd.Timestamp(now, unit="s", tz="UTC"), "asof", pd.Timestamp(asof, unit="s", tz="UTC"))
for sym in ("PF_XBTUSD", "PF_PUMPUSD"):
    c = k.candles(sym, "trade", "1h", asof - 4 * 3600, now + 3600)
    print(sym, "trade candles incl. open hour:\n", c.tail(4))
    for tick in ("mark", "spot"):
        c = k.candles(sym, tick, "1h", asof - 2 * 3600, now + 3600)
        print(sym, tick, list(c.index.strftime("%H:%M")))
    for kind in ANALYTICS:
        a = k.analytics(sym, kind, asof - 3 * 3600, now + 3600)
        print(sym, kind, "rows:", [(t.strftime("%H:%M"), [round(float(v), 6) for v in r]) for t, r in zip(a.index, a.to_numpy())][-4:])
    f = k.funding_history(sym)
    print(sym, "funding tail:", [(t.strftime("%d %H:%M"), float(v)) for t, v in f["funding_rel"].tail(3).items()], "rows", len(f))
    t0, c0 = time.time(), k.calls
    df, meta = build_symbol(k, sym, asof, asof - 3000 * 3600)
    print(sym, "build_symbol 3000 bars:", round(time.time() - t0, 1), "s", k.calls - c0, "calls", meta)
    print(df.tail(3).T)
    print("NaN share in last 24 rows:", df.tail(24).isna().mean().round(2).to_dict())
