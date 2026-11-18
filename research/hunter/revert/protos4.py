"""More prototypes (research only): market-wide cascade, OI wipe-out, flush + resting bid."""
from __future__ import annotations
import numpy as np, pandas as pd
from protos2 import *

BTC = "PF_XBTUSD"


class Cascade(Strategy):
    """Market-wide liquidation cascade: the coin AND bitcoin are both down hard over k bars -> long."""
    name = "revert_cascade"
    valid_bars = 1
    max_hold = 12
    params = {"k": 6, "z": 4.0, "zb": 3.0, "stop_atr": 4.0, "lim_atr": 0.0, "tp_atr": 0.0}

    def intents(self, data, p):
        out = {}
        k = int(p["k"])
        zb = mz(data[BTC], k)
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            z = mz(df, k)
            b = zb.reindex(df.index)
            long = (z < -p["z"]) & (b < -p["zb"]) & atr.notna() & print_ok(df)
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            ref = c
            if p.get("lim_atr", 0):
                ref = c - p["lim_atr"] * atr
                it["limit"] = np.where(long, ref, np.nan)
            it["stop"] = np.where(long, ref - p["stop_atr"] * atr, np.nan)
            if p.get("tp_atr", 0):
                it["tp"] = np.where(long, ref + p["tp_atr"] * atr, np.nan)
            out[sym] = it
        return out


class OIWipe(Strategy):
    """Open interest collapses while price drops: forced long liquidation has finished -> long."""
    name = "revert_oi_wipe"
    valid_bars = 1
    max_hold = 12
    params = {"k": 3, "z": 3.0, "q": 0.01, "stop_atr": 4.0}

    def intents(self, data, p):
        out = {}
        k = int(p["k"])
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            doi = df["oi"] / df["oi"].shift(k) - 1
            thr = doi.rolling(720, min_periods=240).quantile(p["q"]).shift(1)
            long = (doi < thr) & (mz(df, k) < -p["z"]) & atr.notna() & print_ok(df) & df["oi"].notna()
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            out[sym] = it
        return out


class FlushBid(Strategy):
    """After a liquidation flush bar, work a resting bid lim_atr*ATR below the close for a few bars."""
    name = "revert_flush_bid"
    valid_bars = 3
    max_hold = 12
    params = {"z": 2.0, "liq_mult": 1.0, "lim_atr": 1.0, "stop_atr": 3.0, "tp_atr": 2.0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            liq = df["liq_vol"] * c
            q = liq.rolling(720, min_periods=240).quantile(0.99).shift(1)
            long = (liq > p["liq_mult"] * q) & (q > 0) & (mz(df, 1) < -p["z"]) & atr.notna() & print_ok(df)
            lim = c - p["lim_atr"] * atr
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["limit"] = np.where(long, lim, np.nan)
            it["stop"] = np.where(long, lim - p["stop_atr"] * atr, np.nan)
            if p.get("tp_atr", 0):
                it["tp"] = np.where(long, lim + p["tp_atr"] * atr, np.nan)
            out[sym] = it
        return out
