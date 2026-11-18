"""Crash bid: resting limit far below the close, only after a directional 48h (research only)."""
from __future__ import annotations
import numpy as np, pandas as pd
from protos2 import *


class CrashBid(Strategy):
    name = "revert_crash_bid"
    valid_bars = 1
    max_hold = 12
    params = {"er_n": 48, "er_min": 0.35, "lim_atr": 3.0, "stop_atr": 4.0, "tp_atr": 0.0, "trend": "any"}

    def intents(self, data, p):
        out = {}
        n = int(p["er_n"])
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            er = ta.efficiency_ratio(c, n)
            ok = (er > p["er_min"]) & atr.notna() & print_ok(df) & (df["volume"] > 0)
            if p.get("trend") == "up":
                ok &= c > c.shift(n)
            elif p.get("trend") == "down":
                ok &= c < c.shift(n)
            lim = c - p["lim_atr"] * atr
            it["side"] = np.where(ok, 1, 0).astype(np.int8)
            it["limit"] = np.where(ok, lim, np.nan)
            it["stop"] = np.where(ok, lim - p["stop_atr"] * atr, np.nan)
            if p.get("tp_atr", 0):
                it["tp"] = np.where(ok, lim + p["tp_atr"] * atr, np.nan)
            out[sym] = it
        return out
