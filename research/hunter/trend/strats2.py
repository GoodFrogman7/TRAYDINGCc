"""Round-2 candidates: limit-entry pullbacks, breakout retest, strong time-series momentum."""
from __future__ import annotations
import numpy as np, pandas as pd
from lib import ta, BTC
from desk.strategies.base import Strategy, blank_intents
from strats import _btc_on


class PullbackLimit(Strategy):
    """With coin+BTC L-bar trend agreeing, rest a limit x ATR beyond the N-bar extreme on the pullback side."""
    name = "trend_flush_limit"
    regime = "trending"
    valid_bars = 1
    max_hold = 24
    params = {"L": 336, "N": 48, "x": 1.0, "stop_atr": 2.5, "tp_atr": 0.0, "sides": 0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            tr = np.sign(ta.ret(c, p["L"]))
            bt = _btc_on(data, df.index, lambda b: np.sign(ta.ret(b["close"], p["L"])))
            lo = df["low"].rolling(p["N"], min_periods=p["N"]).min()      # includes bar t (known at its close)
            hi = df["high"].rolling(p["N"], min_periods=p["N"]).max()
            ok = atr.notna() & lo.notna()
            long = ok & (tr > 0) & (bt > 0)
            short = ok & (tr < 0) & (bt < 0)
            if p.get("sides", 0) == 1: short &= False
            if p.get("sides", 0) == -1: long &= False
            side = np.where(long, 1, np.where(short, -1, 0))
            lim = np.where(side > 0, lo - p["x"] * atr, hi + p["x"] * atr)
            it["side"] = side.astype(np.int8)
            it["limit"] = np.where(side != 0, lim, np.nan)
            it["stop"] = np.where(side > 0, lim - p["stop_atr"] * atr, lim + p["stop_atr"] * atr)
            if p.get("tp_atr", 0) > 0:
                it["tp"] = np.where(side > 0, lim + p["tp_atr"] * atr, np.where(side < 0, lim - p["tp_atr"] * atr, np.nan))
            out[sym] = it
        return out


class BreakRetest(Strategy):
    """After a close through the N-bar extreme WITH the trend, rest a limit at the broken level (retest entry)."""
    name = "trend_break_retest"
    regime = "trending"
    valid_bars = 24
    max_hold = 72
    params = {"L": 336, "N": 168, "stop_atr": 2.5, "sides": 1, "btc": 1}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            tr = np.sign(ta.ret(c, p["L"]))
            bt = _btc_on(data, df.index, lambda b: np.sign(ta.ret(b["close"], p["L"])))
            dh, dl = ta.donchian_high(df, p["N"]), ta.donchian_low(df, p["N"])
            long = (c > dh) & (tr > 0) & atr.notna()
            short = (c < dl) & (tr < 0) & atr.notna()
            if p.get("btc", 1):
                long &= bt > 0; short &= bt < 0
            if p.get("sides", 0) == 1: short &= False
            if p.get("sides", 0) == -1: long &= False
            side = np.where(long, 1, np.where(short, -1, 0))
            lim = np.where(side > 0, dh, dl)
            it["side"] = side.astype(np.int8)
            it["limit"] = np.where(side != 0, lim, np.nan)
            it["stop"] = np.where(side > 0, lim - p["stop_atr"] * atr, lim + p["stop_atr"] * atr)
            out[sym] = it
        return out


class StrongMom(Strategy):
    """Time-series momentum: hold in the direction of a STRONG L-bar return when BTC agrees."""
    name = "trend_tsmom_strong"
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "rank": 0.7, "stop_atr": 5.0, "btc": 1}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            r = ta.ret(c, p["L"])
            rk = ta.rolling_rank(r.abs(), 4320)
            bt = _btc_on(data, df.index, lambda b: np.sign(ta.ret(b["close"], p["L"])))
            strong = (rk >= p["rank"]) & atr.notna()
            long = strong & (r > 0); short = strong & (r < 0)
            if p.get("btc", 1):
                long &= bt > 0; short &= bt < 0
            side = np.where(long, 1, np.where(short, -1, 0))
            it["side"] = side.astype(np.int8)
            it["stop"] = np.where(side > 0, c - p["stop_atr"] * atr, c + p["stop_atr"] * atr)
            out[sym] = it
        return out
