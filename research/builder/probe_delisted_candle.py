"""What exactly is the single candle the live API serves for a DELISTED PF_ contract?
(probe_delisted.py: 'trade candles: 200, 1 candles, last <the hour that just closed>').
Read-only GET requests, no account.     PYTHONPATH=. python research/builder/probe_delisted_candle.py"""
import sys
import time

from desk.data.kraken import KrakenFutures

k = KrakenFutures(timeout=15, max_retries=2)
now = int(time.time()) // 3600 * 3600


def show(c):
    return {**{x: c[x] for x in ("open", "high", "low", "close", "volume")},
            "time": time.strftime("%Y-%m-%d %H:%M", time.gmtime(c["time"] / 1000))}


for sym in sys.argv[1:] or ["PF_FTMUSD", "PF_EOSUSD", "PF_MATICUSD"]:
    print("==", sym)
    for label, frm, to in (("125 d to now", now - 3000 * 3600, now - 1),
                           ("to 10 h ago", now - 3000 * 3600, now - 10 * 3600 - 1),
                           ("one year window ending 30 d ago", now - 395 * 86400, now - 30 * 86400),
                           ("all history", 0, now - 1)):
        try:
            d = k.get(f"/api/charts/v1/trade/{sym}/1h", {"from": frm, "to": to})
            cs = d["candles"]
            print(f"  {label}: {len(cs)} candles, more={d.get('more_candles')}")
            for c in cs[:1] + cs[-2:]:
                print("     ", show(c))
        except Exception as e:
            print(f"  {label}: {type(e).__name__}: {str(e)[:200]}")
