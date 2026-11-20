"""Premium-fade variants (research only)."""
from __future__ import annotations
import numpy as np, pandas as pd
from protos2 import *


class PremiumFade2(Strategy):
    name = "revert_premium_fade2"
    valid_bars = 1
    max_hold = 8
    params = {"prem": 0.003, "stop_atr": 3.0, "sides": "both", "tp_atr": 0.0, "exit_prem": None, "lim_atr": 0.0,
              "skip": ()}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            if sym in p.get("skip", ()):
                out[sym] = it; continue
            c = df["close"]
            atr = ta.atr(df, 24)
            pr = df["premium"]
            ok = atr.notna() & print_ok(df) & pr.notna()
            short = ok & (pr > p["prem"]) & (p["sides"] in ("short", "both"))
            long = ok & (pr < -p["prem"]) & (p["sides"] in ("long", "both"))
            it["side"] = np.where(long, 1, np.where(short, -1, 0)).astype(np.int8)
            ref = c
            if p.get("lim_atr", 0):
                lim = np.where(long, c - p["lim_atr"] * atr, np.where(short, c + p["lim_atr"] * atr, np.nan))
                it["limit"] = lim
                ref = pd.Series(lim, index=df.index)
            it["stop"] = np.where(long, ref - p["stop_atr"] * atr, np.where(short, ref + p["stop_atr"] * atr, np.nan))
            if p.get("tp_atr", 0):
                it["tp"] = np.where(long, ref + p["tp_atr"] * atr, np.where(short, ref - p["tp_atr"] * atr, np.nan))
            if p.get("exit_prem") is not None:
                it["exit"] = (pr.abs() < p["exit_prem"]).fillna(False)
            out[sym] = it
        return out
