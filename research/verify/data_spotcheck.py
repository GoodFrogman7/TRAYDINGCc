"""Spot-check the stored dataset against Kraken's public API (a few dozen calls).

For random symbols (delisted ones included) and random days across 2022-2026, re-fetch one day of hourly
trade candles, mark and spot closes, open interest and liquidation volume, and compare with the parquet files.
Writes research/verify/data_spotcheck.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desk.data import store                       # noqa: E402
from desk.data.kraken import KrakenFutures        # noqa: E402

rng = np.random.default_rng(20261118)
k = KrakenFutures()
syms = ["PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD", "PF_XRPUSD", "PF_EOSUSD", "PF_MATICUSD", "PF_ZECUSD", "PF_SUIUSD"]
rows, worst = [], {}
for s in syms:
    df = store.load(s)
    for _ in range(4):
        t0 = df.index[int(rng.integers(0, len(df) - 30))].floor("D")
        a, b = int(t0.timestamp()), int(t0.timestamp()) + 86400
        mine = df[(df.index >= t0) & (df.index < t0 + pd.Timedelta(days=1))]
        if mine.empty:
            continue
        rec = {"symbol": s, "day": t0.strftime("%Y-%m-%d"), "bars": int(len(mine))}
        api = k.candles(s, "trade", "1h", a, b).reindex(mine.index)
        real = ~mine["bar_missing"].astype(bool)
        for c in ("open", "high", "low", "close", "volume"):
            d = (mine.loc[real, c] - api.loc[real, c]).abs() / mine.loc[real, c].abs().clip(lower=1e-12)
            rec[c] = float(d.max()) if len(d) else 0.0
        for tick in ("mark", "spot"):
            x = k.candles(s, tick, "1h", a, b)["close"].reindex(mine.index)
            d = (mine[f"{tick}_close"] - x).abs() / mine[f"{tick}_close"].abs()
            rec[f"{tick}_close"] = float(d.max()) if d.notna().any() else None
        for kind, col in (("open-interest", "oi"), ("liquidation-volume", "liq_vol")):
            x = k.analytics(s, kind, a, b)
            if len(x) and mine[col].notna().any():
                y = x[col].reindex(mine.index)
                d = (mine[col].astype("float64") - y).abs() / y.abs().clip(lower=1e-9)
                rec[col] = float(d[mine[col].notna() & y.notna()].max()) if (mine[col].notna() & y.notna()).any() else None
            else:
                rec[col] = None
        rec["index_is_bar_open"] = bool((mine.index.minute == 0).all())
        rows.append(rec)
        for c, v in rec.items():
            if isinstance(v, float):
                worst[c] = max(worst.get(c, 0.0), v)
# funding: the venue's actual rates for one symbol versus the stored funding_actual
fr = k.funding_history("PF_ETHUSD")["funding_rel"]
mine = store.load("PF_ETHUSD")["funding_actual"].dropna()
j = fr.reindex(mine.index).dropna()
worst["funding_actual_abs"] = float((mine.reindex(j.index) - j).abs().max())
# sanity of bars
bad = {}
for s in store.symbols():
    df = store.load(s)
    real = ~df["bar_missing"].astype(bool)
    n = int(((df["high"] < df["low"]) | (df["close"] > df["high"] * 1.0000001) | (df["close"] < df["low"] * 0.9999999)
             | (df["low"] <= 0))[real].sum())
    dup = int(df.index.duplicated().sum())
    gaps = int((df.index.to_series().diff().dropna() != pd.Timedelta(hours=1)).sum())
    spikes = int(((df["high"] / df["close"].shift(1) > 1.5) | (df["low"] / df["close"].shift(1) < 0.5))[real].sum())
    if n or dup or gaps or spikes:
        bad[s] = {"ohlc_inconsistent": n, "duplicate_hours": dup, "index_gaps": gaps, "bars_moving_50pct": spikes}
out = {"checked_at_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "source": "https://futures.kraken.com",
       "api_calls": k.calls, "symbol_days_checked": len(rows), "worst_relative_difference": worst,
       "symbols_with_bar_problems": bad, "rows": rows}
Path(__file__).with_name("data_spotcheck.json").write_text(json.dumps(out, indent=1))
print("symbol-days checked:", len(rows), "| api calls:", k.calls)
print("worst relative difference by column:", {c: (f"{v:.2e}" if isinstance(v, float) else v) for c, v in worst.items()})
print("symbols with bar problems:", bad)
