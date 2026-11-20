"""What does the live public API answer for a DELISTED PF_ contract on each endpoint the bot uses?
Read-only GET requests, no account."""
import json
import sys
import time

from desk.data.kraken import KrakenFutures

k = KrakenFutures(timeout=15, max_retries=2)
listed = {i["symbol"] for i in k.instruments()}
seen = json.load(open("data/symbols_seen.json"))
dead = [s for s in seen if s.startswith("PF_") and s not in listed]
print("listed", len(listed), "seen", len(seen), "delisted", len(dead), dead[:8])
now = int(time.time()) // 3600 * 3600
picks = [s for s in ("PF_FTMUSD", "PF_EOSUSD", "PF_MATICUSD", "PF_RNDRUSD") if s in dead][:2] + ["PF_NOSUCHUSD"]
for sym in picks + sys.argv[1:]:
    print("==", sym)
    for name, call in (
        ("trade candles (last 125 d)", lambda: k.get(f"/api/charts/v1/trade/{sym}/1h", {"from": now - 3000 * 3600, "to": now - 1})),
        ("mark candles", lambda: k.get(f"/api/charts/v1/mark/{sym}/1h", {"from": now - 48 * 3600, "to": now - 1})),
        ("spot candles", lambda: k.get(f"/api/charts/v1/spot/{sym}/1h", {"from": now - 48 * 3600, "to": now - 1})),
        ("funding", lambda: k.get("/derivatives/api/v4/historicalfundingrates", {"symbol": sym})),
        ("analytics oi", lambda: k.get(f"/api/charts/v1/analytics/{sym}/open-interest", {"since": now - 48 * 3600, "to": now - 1, "interval": 3600})),
        ("analytics slippage", lambda: k.get(f"/api/charts/v1/analytics/{sym}/slippage", {"since": now - 48 * 3600, "to": now - 1, "interval": 3600})),
    ):
        try:
            d = call()
            if "candles" in d:
                cs = d["candles"]
                last = None if not cs else time.strftime("%Y-%m-%d %H:%M", time.gmtime(cs[-1]["time"] / 1000))
                print(f"  {name}: 200, {len(cs)} candles, last {last}, more={d.get('more_candles')}")
            elif "rates" in d:
                print(f"  {name}: 200, {len(d['rates'] or [])} rates")
            else:
                r = d.get("result") or {}
                print(f"  {name}: 200, {len(r.get('timestamp') or [])} rows, keys {list(d)[:4]}")
        except Exception as e:
            print(f"  {name}: {type(e).__name__}: {str(e)[:160]}")
