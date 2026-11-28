"""FINAL candidate rules, written exactly as on the idea cards (research prototypes, NOT registered with the desk).

Shared definitions (all causal):
  mark      = mark_close
  sig168[t] = std of ln(mark[i]/mark[i-1]) over the 168 bars ending at t-1      (rolling(168).std().shift(1))
  mz(k)[t]  = ln(mark[t]/mark[t-k]) / (sig168[t] * sqrt(k))
  atr[t]    = ta.atr(df, 24)                                                    (Wilder, trade candles)
  print_ok  = abs(close/mark_close - 1) <= 0.003   -> the last print (which IS the next bar's open) agrees with the book
"""
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

BTC = "PF_XBTUSD"


def sig168(df):
    return np.log(df["mark_close"]).diff().rolling(168, min_periods=168).std().shift(1)


def mz(df, k):
    m = df["mark_close"]
    return np.log(m / m.shift(k)) / (sig168(df) * np.sqrt(k))


def print_ok(df, tol=0.003):
    return (df["close"] / df["mark_close"] - 1).abs() <= tol


class PremiumFade(Strategy):
    name = "revert_premium_fade"
    idea = "Fade the perp when its hour-average premium to the spot index is extreme: short when rich, long when cheap."
    regime = "ranging"
    valid_bars = 1
    max_hold = 8
    params = {"prem": 0.003, "stop_atr": 3.0, "exit_prem": 0.001, "sides": "both"}
    grid = {"prem": [0.0025, 0.003, 0.004], "stop_atr": [2.0, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c, pr = df["close"], df["premium"]
            atr = ta.atr(df, 24)
            ok = atr.notna() & pr.notna() & print_ok(df)
            short = ok & (pr > p["prem"]) & (p.get("sides", "both") in ("both", "short"))
            long = ok & (pr < -p["prem"]) & (p.get("sides", "both") in ("both", "long"))
            it["side"] = np.where(long, 1, np.where(short, -1, 0)).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.where(short, c + p["stop_atr"] * atr, np.nan))
            it["exit"] = (pr.abs() < p["exit_prem"]).fillna(False).to_numpy()
            out[sym] = it
        return out


class OIWipe(Strategy):
    name = "revert_oi_wipe"
    idea = "Buy after open interest collapses during a multi-sigma k-bar drop: the forced sellers are gone."
    regime = "wild"
    valid_bars = 1
    max_hold = 12
    needs = ("oi",)
    params = {"k": 3, "z": 3.0, "q": 0.01, "stop_atr": 4.0}
    grid = {"k": [1, 3, 6], "stop_atr": [3.0, 4.0, 5.0]}

    def intents(self, data, p):
        out = {}
        k = int(p["k"])
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            doi = df["oi"] / df["oi"].shift(k) - 1
            thr = doi.rolling(720, min_periods=240).quantile(p["q"]).shift(1)
            long = (doi < thr) & (mz(df, k) < -p["z"]) & atr.notna() & print_ok(df)
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            out[sym] = it
        return out


class Cascade(Strategy):
    name = "revert_cascade"
    idea = "Buy a coin that is down more than z sigma over 6 hours when bitcoin is also down hard over the same 6 hours."
    regime = "wild"
    valid_bars = 1
    max_hold = 12
    params = {"k": 6, "z": 4.0, "zb": 3.0, "stop_atr": 4.0}
    grid = {"z": [4.0, 4.5, 5.0], "zb": [2.0, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        k = int(p["k"])
        zb = mz(data[BTC], k)
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            long = (mz(df, k) < -p["z"]) & (zb.reindex(df.index) < -p["zb"]) & atr.notna() & print_ok(df)
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            out[sym] = it
        return out


class LiqFlush(Strategy):
    name = "revert_liq_flush"
    idea = "Buy after an hour with a liquidation-volume spike and a -3 sigma bar."
    regime = "wild"
    valid_bars = 1
    max_hold = 12
    needs = ("liq_vol",)
    params = {"z": 3.0, "liq_mult": 2.0, "stop_atr": 4.0}
    grid = {"liq_mult": [1.5, 2.0, 3.0], "stop_atr": [3.0, 4.0, 5.0]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            liq = df["liq_vol"] * c
            q99 = liq.rolling(720, min_periods=240).quantile(0.99).shift(1)
            long = (liq > p["liq_mult"] * q99) & (q99 > 0) & (mz(df, 1) < -p["z"]) & atr.notna() & print_ok(df)
            it["side"] = np.where(long, 1, 0).astype(np.int8)
            it["stop"] = np.where(long, c - p["stop_atr"] * atr, np.nan)
            out[sym] = it
        return out


FINAL = [PremiumFade(), OIWipe(), Cascade(), LiqFlush()]
