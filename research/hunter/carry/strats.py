"""Draft strategies for the carry lens (DESIGN-window sanity checks only; the Auditor re-implements)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from desk.strategies import ta
from desk.strategies.base import Strategy, blank_intents


def _finish(it, df, long_sig, short_sig, atr, k):
    side = np.where(long_sig, 1, np.where(short_sig, -1, 0)).astype(np.int8)
    it["side"] = side
    it["stop"] = np.where(side > 0, df["close"] - k * atr, np.where(side < 0, df["close"] + k * atr, np.nan))
    return it


class DiscountBounce(Strategy):
    """Long when the 8h-mean perp premium is unusually deep below its own 30d norm."""
    name = "carry_discount_bounce"
    max_hold = 36
    params = {"pm_n": 8, "z": 2.5, "floor_bp": 5.0, "norm_n": 720, "atr_n": 24, "stop_atr": 3.0, "exit_prem": True}
    grid = {"z": [2.0, 2.5, 3.0], "stop_atr": [2.5, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
            med = pm.rolling(p["norm_n"], min_periods=p["norm_n"] // 2).median()
            sd = df["premium"].rolling(p["norm_n"], min_periods=p["norm_n"] // 2).std()
            z = (pm - med) / sd
            sig = (z <= -p["z"]) & (pm <= -p["floor_bp"] / 1e4) & atr.notna()
            it = _finish(it, df, sig.fillna(False), False, atr, p["stop_atr"])
            if p.get("exit_prem"):
                it["exit"] = (pm >= med).fillna(False)          # discount closed -> cause gone
            out[s] = it
        return out


class DiscountAbs(Strategy):
    name = "carry_discount_abs"
    max_hold = 36
    params = {"pm_n": 8, "thr_bp": 12.0, "atr_n": 24, "stop_atr": 3.0}
    grid = {"thr_bp": [8.0, 12.0, 16.0], "stop_atr": [2.5, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
            sig = (pm <= -p["thr_bp"] / 1e4) & atr.notna()
            out[s] = _finish(it, df, sig.fillna(False), False, atr, p["stop_atr"])
        return out


class HotDip(Strategy):
    """Long a new N-bar closing low while the 24h-mean premium is rich."""
    name = "carry_hot_dip"
    max_hold = 24
    params = {"pm_n": 24, "thr_bp": 5.0, "don_n": 24, "atr_n": 24, "stop_atr": 3.0}
    grid = {"thr_bp": [3.0, 5.0, 8.0], "don_n": [12, 24, 48], "stop_atr": [2.5, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
            sig = (df["close"] < ta.donchian_low(df, p["don_n"])) & (pm >= p["thr_bp"] / 1e4) & atr.notna()
            out[s] = _finish(it, df, sig.fillna(False), False, atr, p["stop_atr"])
        return out


class OIWashout(Strategy):
    """Long a new N-bar closing low when open interest has been flushed."""
    name = "carry_oi_washout"
    max_hold = 36
    needs = ("oi",)
    params = {"don_n": 72, "oi_n": 24, "oi_drop": 0.15, "atr_n": 24, "stop_atr": 3.0}
    grid = {"oi_drop": [0.10, 0.15, 0.20], "don_n": [48, 72, 96], "stop_atr": [2.5, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            d = df["oi"] / df["oi"].shift(p["oi_n"]) - 1
            sig = (df["close"] < ta.donchian_low(df, p["don_n"])) & (d <= -p["oi_drop"]) & atr.notna()
            out[s] = _finish(it, df, sig.fillna(False), False, atr, p["stop_atr"])
        return out


class RetailCap(Strategy):
    """Long when the share of accounts net long is at a trailing-30d low after a 24h drop."""
    name = "carry_retail_capitulation"
    max_hold = 24
    needs = ("ls_ratio",)
    params = {"q": 0.10, "drop": 0.03, "rank_n": 720, "atr_n": 24, "stop_atr": 3.0}
    grid = {"q": [0.05, 0.10, 0.20], "drop": [0.02, 0.03, 0.05], "stop_atr": [2.5, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            rk = df["ls_ratio"].rolling(p["rank_n"], min_periods=p["rank_n"] // 2).rank(pct=True)
            sig = (rk <= p["q"]) & ((df["close"] / df["close"].shift(24) - 1) <= -p["drop"]) & atr.notna()
            out[s] = _finish(it, df, sig.fillna(False), False, atr, p["stop_atr"])
        return out


class PremSpikeShort(Strategy):
    """NEAR-MISS: short an extreme 1h premium spike."""
    name = "carry_premium_spike_short"
    max_hold = 8
    params = {"thr_bp": 40.0, "atr_n": 24, "stop_atr": 3.0}
    grid = {"thr_bp": [20.0, 40.0, 60.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            sig = (df["premium"] >= p["thr_bp"] / 1e4) & atr.notna()
            out[s] = _finish(it, df, False, sig.fillna(False), atr, p["stop_atr"])
        return out


# ---------------------------------------------------------------- execution variants (one shared wrapper)
def _state_signals(df, p, kind):
    """Raw condition per bar for the three long setups."""
    if kind == "oi":
        d = df["oi"] / df["oi"].shift(p["oi_n"]) - 1
        return (df["close"] < ta.donchian_low(df, p["don_n"])) & (d <= -p["oi_drop"])
    if kind == "disc":
        pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
        med = pm.rolling(p["norm_n"], min_periods=p["norm_n"] // 2).median()
        sd = df["premium"].rolling(p["norm_n"], min_periods=p["norm_n"] // 2).std()
        return ((pm - med) / sd <= -p["z"]) & (pm <= -p["floor_bp"] / 1e4)
    if kind == "hot":
        pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
        return (df["close"] < ta.donchian_low(df, p["don_n"])) & (pm >= p["thr_bp"] / 1e4)
    raise ValueError(kind)


class Variant(Strategy):
    """mode: 'mkt' market on signal | 'turn' wait for a turn bar | 'limit' resting bid below | 'first' first signal in cool bars."""
    def __init__(self, kind, mode, name, max_hold, valid_bars=1, **params):
        self.kind, self.mode, self.name, self.max_hold, self.valid_bars = kind, mode, name, max_hold, valid_bars
        base = {"atr_n": 24, "stop_atr": 3.0, "arm": 12, "cool": 24, "lim_atr": 1.5,
                "oi_n": 24, "oi_drop": 0.15, "don_n": 72, "pm_n": 8, "z": 2.5, "floor_bp": 5.0, "norm_n": 720, "thr_bp": 5.0}
        base.update(params)
        self.params = base

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            raw = _state_signals(df, p, self.kind).fillna(False) & atr.notna()
            c = df["close"]
            if self.mode == "mkt":
                sig = raw
                stop = c - p["stop_atr"] * atr
            elif self.mode == "first":
                prev = raw.shift(1).rolling(p["cool"], min_periods=1).max().fillna(0).astype(bool)
                sig = raw & ~prev
                stop = c - p["stop_atr"] * atr
            elif self.mode == "turn":
                armed = raw.shift(1).rolling(p["arm"], min_periods=1).max().fillna(0).astype(bool)   # condition seen in the previous arm bars
                turn = (c > df["high"].shift(1)) & (c > df["open"])
                sig = armed & turn
                swing = df["low"].rolling(p["arm"] + 1, min_periods=1).min()
                stop = swing - 0.5 * atr
            elif self.mode == "limit":
                sig = raw
                it["limit"] = np.where(sig, c - p["lim_atr"] * atr, np.nan)
                stop = c - (p["lim_atr"] + p["stop_atr"]) * atr
            it["side"] = np.where(sig, 1, 0).astype(np.int8)
            it["stop"] = np.where(sig, stop, np.nan)
            out[s] = it
        return out
