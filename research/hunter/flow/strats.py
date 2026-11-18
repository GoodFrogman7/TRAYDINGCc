"""Draft implementations of the flow-lens ideas, written against the desk Strategy contract so the
design-window engine check uses the same fills, costs and Guardian as the Auditor will. NOT registered."""
from __future__ import annotations
import numpy as np
import pandas as pd
from desk.strategies import ta
from desk.strategies.base import Strategy, blank_intents

BTC = "PF_XBTUSD"


def rz(close: pd.Series, n: int = 168) -> pd.Series:
    """1-bar return divided by the std of the PREVIOUS n 1-bar returns."""
    r = close / close.shift(1) - 1.0
    sd = r.rolling(n, min_periods=100).std().shift(1)
    return r / sd


def liq_spike(df: pd.DataFrame, q: float = 0.99, n: int = 720) -> pd.Series:
    liq = df["liq_vol"].fillna(0.0)
    thr = liq.rolling(n, min_periods=n // 2).quantile(q).shift(1)
    return (liq > thr) & (liq > 0)


def vol_rel(df: pd.DataFrame, n: int = 168) -> pd.Series:
    med = df["volume"].rolling(n, min_periods=100).median().shift(1)
    return df["volume"] / med.replace(0, np.nan)


def _long(it, sig, df, atr, stop_atr, tp_atr=None, limit_atr=None):
    """Long intent. limit_atr=None -> market at next open, stop = close - stop_atr*ATR.
    limit_atr=d -> resting buy limit at close - d*ATR, stop = limit - stop_atr*ATR, tp = limit + tp_atr*ATR."""
    sig = sig.fillna(False) & atr.notna()
    it["side"] = np.where(sig, 1, 0).astype(np.int8)
    ref = df["close"]
    if limit_atr is not None:
        ref = df["close"] - limit_atr * atr
        it["limit"] = ref
    it["stop"] = ref - stop_atr * atr
    if stop_atr < 0:                      # negative value = fixed-percentage stop, e.g. -0.08 -> 8% below the reference
        it["stop"] = ref * (1.0 + stop_atr)
    if tp_atr:
        it["tp"] = ref + tp_atr * atr
    return it


class BtcLiqFlush(Strategy):
    name = "flow_btc_liq_flush"
    max_hold = 12
    params = {"z": 3.0, "liq_q": 0.99, "stop_atr": 2.5}
    grid = {"z": [2.5, 3.0, 3.5], "stop_atr": [2.0, 2.5, 3.0]}
    needs = ("liq_vol",)

    def intents(self, data, p):
        b = data[BTC]
        bsig = liq_spike(b, p["liq_q"]) & (rz(b["close"]) <= -p["z"])
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            sig = bsig.reindex(df.index).fillna(False) & (rz(df["close"]) <= -p["z"])
            out[s] = _long(it, sig, df, ta.atr(df, 24), p["stop_atr"], p.get("tp_atr"), p.get("limit_atr"))
        return out


class HotVolBreakdownFade(Strategy):
    name = "flow_hot_breakdown_fade"
    max_hold = 24
    params = {"n": 48, "rank_min": 0.5, "stop_atr": 2.5}
    grid = {"n": [36, 48, 72], "rank_min": [0.4, 0.5, 0.7], "stop_atr": [2.0, 2.5, 3.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            rank = ta.rolling_rank(ta.bb_width(df["close"], 48, 2.0), 720).shift(1)
            sig = (df["close"] < ta.donchian_low(df, p["n"])) & (rank > p["rank_min"])
            if p.get("vmax"):
                sig &= vol_rel(df) <= p["vmax"]
            out[s] = _long(it, sig, df, ta.atr(df, 24), p["stop_atr"], p.get("tp_atr"), p.get("limit_atr"))
        return out


class LiquidityVacuumFade(Strategy):
    name = "flow_liquidity_vacuum_fade"
    max_hold = 24
    params = {"sp_mult": 2.0, "drop_atr": 2.0, "stop_atr": 2.5}
    grid = {"sp_mult": [1.5, 2.0, 3.0], "drop_atr": [1.5, 2.0, 2.5], "stop_atr": [2.0, 2.5, 3.0]}
    needs = ("bid_10k", "ask_10k")

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            if "bid_10k" not in df:
                out[s] = it; continue
            half = (df["ask_10k"] - df["bid_10k"]) / (df["ask_10k"] + df["bid_10k"])
            half = half.where(half > 0)
            rel = half / half.rolling(168, min_periods=48).median().shift(1)
            atr = ta.atr(df, 24)
            sig = (rel >= p["sp_mult"]) & ((df["close"].shift(4) - df["close"]) > p["drop_atr"] * atr)
            out[s] = _long(it, sig, df, atr, p["stop_atr"], p.get("tp_atr"), p.get("limit_atr"))
        return out


class AirPocketFade(Strategy):
    name = "flow_air_pocket_fade"
    max_hold = 12
    params = {"z": 3.0, "vmax": 4.0, "stop_atr": 2.5}
    grid = {"z": [2.5, 3.0, 3.5], "vmax": [2.5, 4.0, 6.0], "stop_atr": [2.0, 2.5, 3.0]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            sig = (rz(df["close"]) <= -p["z"]) & (rz(df["mark_close"]) <= -p["z"]) & (vol_rel(df) <= p["vmax"])
            out[s] = _long(it, sig, df, ta.atr(df, 24), p["stop_atr"], p.get("tp_atr"), p.get("limit_atr"))
        return out


class WeekendDumpShort(Strategy):
    """Weekend (Fri 22:00 -> Sun 22:00 UTC) move continues when weekday liquidity returns.
    dirn=-1 short after a down weekend (default), +1 long after an up weekend, 0 both."""
    name = "flow_weekend_dump_short"
    max_hold = 24
    params = {"z": 0.75, "hour": 21, "stop_atr": 3.0, "dirn": -1}
    grid = {"z": [0.75, 1.0, 1.25], "hour": [17, 21, 23], "stop_atr": [2.5, 3.0, 3.5]}

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            r = df["close"] / df["close"].shift(1) - 1.0
            sd = r.rolling(168, min_periods=100).std().shift(1)
            z = (df["close"] / df["close"].shift(48) - 1.0) / (sd * np.sqrt(48))
            atr = ta.atr(df, 24)
            when = (df.index.dayofweek == 6) & (df.index.hour == p["hour"])
            dn = (z <= -p["z"]) & when & atr.notna() & (p.get("dirn", -1) <= 0)
            up = (z >= p["z"]) & when & atr.notna() & (p.get("dirn", -1) >= 0)
            it["side"] = np.where(dn, -1, np.where(up, 1, 0)).astype(np.int8)
            it["stop"] = np.where(up, df["close"] - p["stop_atr"] * atr, df["close"] + p["stop_atr"] * atr)
            out[s] = it
        return out


class StressBid(Strategy):
    """BTC dumps on a volume surge; an alt that refuses to follow is bought."""
    name = "flow_stress_bid"
    max_hold = 24
    params = {"z_btc": 3.0, "v_btc": 3.0, "z_alt": -1.0, "stop_atr": 3.0}
    grid = {"z_btc": [2.5, 3.0, 3.5], "z_alt": [-1.0, -0.5, 0.0], "stop_atr": [2.5, 3.0, 4.0]}
    EXCLUDE = ("PF_XBTUSD", "PF_ETHUSD")

    def intents(self, data, p):
        b = data[BTC]
        bsig = (rz(b["close"]) <= -p["z_btc"]) & (vol_rel(b) >= p["v_btc"])
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            if s in self.EXCLUDE:
                out[s] = it; continue
            sig = bsig.reindex(df.index).fillna(False) & (rz(df["close"]) > p["z_alt"])
            out[s] = _long(it, sig, df, ta.atr(df, 24), p["stop_atr"], p.get("tp_atr"), p.get("limit_atr"))
        return out
