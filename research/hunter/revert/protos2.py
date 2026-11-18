"""Prototype strategies, mark-price signals (research only, NOT registered with the desk)."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from desk.strategies import ta
from desk.strategies.base import Strategy, blank_intents


def msig(df, n=168):
    """Std of hourly MARK log returns over the n bars before bar t (excludes bar t)."""
    return np.log(df["mark_close"]).diff().rolling(n, min_periods=n).std().shift(1)


def mz(df, k, n=168):
    m = df["mark_close"]
    return np.log(m / m.shift(k)) / (msig(df, n) * np.sqrt(k))


def print_ok(df, tol=0.003):
    """Last traded close agrees with the mark (the 'next open' the engine fills at is this close)."""
    return (df["close"] / df["mark_close"] - 1).abs() <= tol


class Capitulation(Strategy):
    name = "revert_capitulation"
    valid_bars = 1
    max_hold = 24
    params = {"k": 6, "z": 5.0, "stop_atr": 3.0, "tp_atr": 0.0, "top_n": 0}

    def intents(self, data, p):
        out, zs = {}, {}
        for sym, df in data.items():
            zs[sym] = mz(df, int(p["k"]))
        rank = None
        if p.get("top_n", 0):
            Z = pd.DataFrame(zs)
            rank = Z.where(Z < -p["z"]).rank(axis=1, method="first")   # 1 = most negative
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            long = (zs[sym] < -p["z"]) & atr.notna() & print_ok(df)
            if rank is not None:
                long &= (rank[sym].reindex(df.index) <= p["top_n"])
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            if p.get("tp_atr", 0):
                it["tp"] = np.where(long, c + p["tp_atr"] * atr, np.nan)
            out[sym] = it
        return out


class LiqFlush(Strategy):
    name = "revert_liq_flush"
    valid_bars = 1
    max_hold = 12
    params = {"z": 3.0, "liq_mult": 2.0, "stop_atr": 3.0, "tp_atr": 0.0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            z1 = mz(df, 1)
            atr = ta.atr(df, 24)
            liq = df["liq_vol"] * c
            q = liq.rolling(720, min_periods=240).quantile(0.99).shift(1)
            long = (liq > p["liq_mult"] * q) & (q > 0) & (z1 < -p["z"]) & atr.notna() & print_ok(df)
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            if p.get("tp_atr", 0):
                it["tp"] = np.where(long, c + p["tp_atr"] * atr, np.nan)
            out[sym] = it
        return out


class PremiumFade(Strategy):
    """Perp rich/cheap vs the spot index -> fade back toward the index."""
    name = "revert_premium_fade"
    valid_bars = 1
    max_hold = 8
    params = {"prem": 0.003, "stop_atr": 3.0, "sides": "short", "tp_atr": 0.0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            ok = atr.notna() & print_ok(df) & df["premium"].notna()
            short = ok & (df["premium"] > p["prem"]) & (p["sides"] in ("short", "both"))
            long = ok & (df["premium"] < -p["prem"]) & (p["sides"] in ("long", "both"))
            it["side"] = np.where(long, 1, np.where(short, -1, 0)).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.where(short, c + p["stop_atr"] * atr, np.nan))
            if p.get("tp_atr", 0):
                it["tp"] = np.where(long, c + p["tp_atr"] * atr, np.where(short, c - p["tp_atr"] * atr, np.nan))
            out[sym] = it
        return out
