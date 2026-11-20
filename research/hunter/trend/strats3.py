"""Round-3 candidates: daily-scale with-trend impulse ("trend day") and weekly cross-sectional relative strength."""
from __future__ import annotations
import numpy as np, pandas as pd
from lib import ta, BTC, store
from desk.strategies.base import Strategy, blank_intents
from strats import _btc_on


class TrendDay(Strategy):
    """A >k-sigma 24h move on >v x normal 24h volume, in the direction of the prior L-bar trend -> ride it for a week."""
    name = "trend_day_follow"
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "k": 2.0, "v": 2.0, "stop_atr": 5.0, "sides": 0, "btc": 0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            r24 = c / c.shift(24) - 1
            sd = r24.rolling(720, min_periods=360).std().shift(24)
            v24 = df["volume"].rolling(24, min_periods=24).sum()
            vr = v24 / v24.shift(24).rolling(720, min_periods=360).mean()
            tr = np.sign(ta.ret(c, p["L"]).shift(24))
            big = (r24.abs() > p["k"] * sd) & (vr > p["v"]) & (np.sign(r24) == tr) & atr.notna()
            long = big & (tr > 0); short = big & (tr < 0)
            if p.get("btc", 0):
                bt = _btc_on(data, df.index, lambda b: np.sign(ta.ret(b["close"], p["L"])))
                long &= bt > 0; short &= bt < 0
            if p.get("sides", 0) == 1: short &= False
            if p.get("sides", 0) == -1: long &= False
            side = np.where(long, 1, np.where(short, -1, 0))
            it["side"] = side.astype(np.int8)
            it["stop"] = np.where(side > 0, c - p["stop_atr"] * atr, c + p["stop_atr"] * atr)
            out[sym] = it
        return out


class XSMom(Strategy):
    """Weekly: long the `top` strongest / short the `top` weakest of the month's top-10 by L-bar return."""
    name = "trend_xs_relstrength"
    regime = "trending"
    valid_bars = 1
    max_hold = 167
    params = {"L": 336, "top": 2, "stop_atr": 6.0, "sides": 0, "dow": 6}

    def intents(self, data, p):
        idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
        r = pd.DataFrame({s: ta.ret(df["close"], p["L"]) for s, df in data.items()}).reindex(idx)
        trd = pd.DataFrame({s: store.tradable_mask(s, df.index) for s, df in data.items()}).reindex(idx).fillna(False).astype(bool)
        r = r.where(trd)
        n_ok = r.notna().sum(axis=1)
        rk_hi = r.rank(axis=1, ascending=False)   # 1 = strongest
        rk_lo = r.rank(axis=1, ascending=True)    # 1 = weakest
        when = (idx.dayofweek == p["dow"]) & (idx.hour == 23)
        gate = pd.Series(when, index=idx) & (n_ok >= 8)
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            g = gate.reindex(df.index).fillna(False) & atr.notna()
            long = g & (rk_hi[sym].reindex(df.index) <= p["top"])
            short = g & (rk_lo[sym].reindex(df.index) <= p["top"])
            if p.get("sides", 0) == 1: short &= False
            if p.get("sides", 0) == -1: long &= False
            side = np.where(long, 1, np.where(short, -1, 0))
            it["side"] = side.astype(np.int8)
            it["stop"] = np.where(side > 0, c - p["stop_atr"] * atr, c + p["stop_atr"] * atr)
            out[sym] = it
        return out
