"""Breadth-confirmed discount drafts (DESIGN-window sanity checks only; the Auditor re-implements)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from desk.data import store
from desk.strategies import ta
from desk.strategies.base import Strategy, blank_intents


def zpanel(data, p):
    """Per-symbol z of the pm_n-bar mean premium vs its own trailing norm, and breadth over the point-in-time tradable set."""
    Z, PM = {}, {}
    for s, df in data.items():
        pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
        med = pm.rolling(p["norm_n"], min_periods=p["norm_n"] // 2).median()
        sd = df["premium"].rolling(p["norm_n"], min_periods=p["norm_n"] // 2).std()
        Z[s] = (pm - med) / sd; PM[s] = pm
    idx = sorted(set().union(*[df.index for df in data.values()]))
    idx = pd.DatetimeIndex(idx)
    cnt = pd.Series(0, index=idx, dtype="int64")
    for s, df in data.items():
        tr = store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool)
        hit = ((Z[s] <= -p["zb"]) & tr).astype("int64")
        cnt = cnt.add(hit.reindex(idx, fill_value=0), fill_value=0)
    return Z, PM, cnt


class BreadthDiscount(Strategy):
    """Long a symbol whose perp trades at an unusual discount, only when >= k tradable symbols are at a discount together."""
    name = "carry_cascade_discount"
    max_hold = 36
    params = {"pm_n": 8, "norm_n": 720, "z": 2.0, "zb": 2.0, "k": 2, "atr_n": 24, "stop_atr": 3.0, "mode": "mkt", "arm": 12, "cool": 24, "neg": True, "who": "all"}

    def __init__(self, max_hold=36, **kw):
        self.max_hold = max_hold
        self.params = {**BreadthDiscount.params, **kw}

    def intents(self, data, p):
        Z, PM, cnt = zpanel(data, p)
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            b = cnt.reindex(df.index).fillna(0)
            if p["who"] == "maj_breadth_only":       # market-level play on BTC/ETH: breadth alone
                raw = (b >= p["k"]) if s in ("PF_XBTUSD", "PF_ETHUSD") else pd.Series(False, index=df.index)
            elif p["who"] == "breadth_only":
                raw = (b >= p["k"])
            else:
                raw = (Z[s] <= -p["z"]) & (b >= p["k"])
                if p["neg"]:
                    raw &= PM[s] < 0
            raw = raw.fillna(False) & atr.notna()
            c = df["close"]
            if p["mode"] == "mkt":
                sig = raw; stop = c - p["stop_atr"] * atr
            elif p["mode"] == "first":
                prev = raw.shift(1).rolling(p["cool"], min_periods=1).max().fillna(0).astype(bool)
                sig = raw & ~prev; stop = c - p["stop_atr"] * atr
            else:  # turn
                armed = raw.shift(1).rolling(p["arm"], min_periods=1).max().fillna(0).astype(bool)
                turn = (c > df["high"].shift(1)) & (c > df["open"])
                sig = armed & turn
                stop = df["low"].rolling(p["arm"] + 1, min_periods=1).min() - 0.5 * atr
            it["side"] = np.where(sig, 1, 0).astype(np.int8)
            it["stop"] = np.where(sig, stop, np.nan)
            out[s] = it
        return out
