"""Prototype strategies (research only, NOT registered with the desk). Exact rules mirror the idea cards."""
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


def _sig(df, n=168):
    """Std of hourly log returns over the n bars BEFORE bar t."""
    return np.log(df["close"]).diff().rolling(n, min_periods=n).std().shift(1)


class LiqFlush(Strategy):
    name = "revert_liq_flush"
    valid_bars = 1
    max_hold = 12
    params = {"z": 3.0, "liq_q": 0.99, "stop_atr": 3.0, "sides": "long"}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            z1 = np.log(c).diff() / _sig(df)
            atr = ta.atr(df, 24)
            liq = df["liq_vol"] * c
            q = liq.rolling(720, min_periods=240).quantile(p["liq_q"]).shift(1)
            flush = (liq > q) & (q > 0) & atr.notna()
            long = flush & (z1 < -p["z"])
            short = flush & (z1 > p["z"]) & (p["sides"] == "both")
            it["side"] = np.where(long, 1, np.where(short, -1, 0)).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.where(short, c + p["stop_atr"] * atr, np.nan))
            out[sym] = it
        return out


class Capitulation(Strategy):
    """k-bar return below -z sigma*sqrt(k) -> long."""
    name = "revert_capitulation"
    valid_bars = 1
    max_hold = 12
    params = {"k": 6, "z": 4.0, "stop_atr": 3.0}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            k = int(p["k"])
            zk = np.log(c / c.shift(k)) / (_sig(df) * np.sqrt(k))
            atr = ta.atr(df, 24)
            long = (zk < -p["z"]) & atr.notna()
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            out[sym] = it
        return out
