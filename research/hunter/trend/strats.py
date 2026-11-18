"""Candidate strategies written against the desk Strategy contract (kept OUT of desk/; research copies only)."""
from __future__ import annotations
import numpy as np, pandas as pd
from lib import ta, BTC
from desk.strategies.base import Strategy, blank_intents


def _btc_on(data, index, fn):
    return fn(data[BTC]).reindex(index).ffill()


class Pullback(Strategy):
    """Fade a close through the prior N-bar extreme when it goes AGAINST the L-bar trend of both coin and BTC."""
    name = "trend_pullback"
    regime = "trending"
    valid_bars = 1
    max_hold = 24
    params = {"L": 336, "N": 48, "stop_atr": 2.5, "sides": 0, "tp_atr": 0.0, "slow": 0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            tr = np.sign(ta.ret(c, p["L"]))
            bt = _btc_on(data, df.index, lambda b: np.sign(ta.ret(b["close"], p["L"])))
            ok = atr.notna() & tr.notna() & bt.notna()
            lo = c < ta.donchian_low(df, p["N"])
            hi = c > ta.donchian_high(df, p["N"])
            long = ok & lo & (tr > 0) & (bt > 0)
            short = ok & hi & (tr < 0) & (bt < 0)
            if p.get("slow", 0):
                reg = _btc_on(data, df.index, lambda b: np.sign(b["close"] / ta.sma(b["close"], p["slow"]) - 1))
                long &= reg > 0
                short &= reg < 0
            if p.get("sides", 0) == 1:
                short &= False
            if p.get("sides", 0) == -1:
                long &= False
            side = np.where(long, 1, np.where(short, -1, 0))
            it["side"] = side.astype(np.int8)
            it["stop"] = np.where(side > 0, c - p["stop_atr"] * atr, c + p["stop_atr"] * atr)
            if p.get("tp_atr", 0) > 0:
                it["tp"] = np.where(side > 0, c + p["tp_atr"] * atr, np.where(side < 0, c - p["tp_atr"] * atr, np.nan))
            out[sym] = it
        return out


class Impulse(Strategy):
    """After a high-volume impulse bar, enter in the direction of the L-bar trend (follow if with trend, fade if against)."""
    name = "trend_impulse"
    regime = "trending"
    valid_bars = 1
    max_hold = 72
    params = {"L": 336, "k": 2.5, "v": 3.0, "stop_atr": 3.0, "mode": 0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            a1 = atr.shift(1)
            mv = (c - df["open"]) / a1
            vol = df["volume"] / ta.sma(df["volume"], 168).shift(1)
            tr = np.sign(ta.ret(c, p["L"]).shift(1))
            big = (mv.abs() > p["k"]) & (vol > p["v"]) & atr.notna() & tr.notna()
            d = np.sign(mv)
            if p.get("mode", 0) == 1:
                big &= d == tr
            if p.get("mode", 0) == -1:
                big &= d == -tr
            side = np.where(big & (tr > 0), 1, np.where(big & (tr < 0), -1, 0))
            it["side"] = side.astype(np.int8)
            it["stop"] = np.where(side > 0, c - p["stop_atr"] * atr, c + p["stop_atr"] * atr)
            out[sym] = it
        return out


class BreakoutBull(Strategy):
    """Long a close above the prior N-bar high when coin L-bar return > 0 and BTC is above its slow SMA; ATR trail."""
    name = "trend_breakout_bull"
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "N": 168, "slow": 2160, "stop_atr": 4.0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            tr = ta.ret(c, p["L"])
            reg = _btc_on(data, df.index, lambda b: b["close"] / ta.sma(b["close"], p["slow"]) - 1)
            brk = (c > ta.donchian_high(df, p["N"])) & (tr > 0) & (reg > 0) & atr.notna()
            it["side"] = np.where(brk, 1, 0).astype(np.int8)
            it["stop"] = c - p["stop_atr"] * atr
            it["trail"] = df["high"].rolling(24, min_periods=1).max() - p["stop_atr"] * atr
            out[sym] = it
        return out
