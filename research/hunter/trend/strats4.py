"""Round-4: quiet (efficient) trend continuation; hourly impulse with a per-bar breadth cap."""
from __future__ import annotations
import numpy as np, pandas as pd
from lib import ta, BTC, store
from desk.strategies.base import Strategy, blank_intents
from strats import Impulse


class QuietTrend(Strategy):
    """Enter with the L-bar trend when its Kaufman efficiency ratio is in the top (1-q) of its trailing 180 days."""
    name = "trend_quiet_grind"
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "q": 0.8, "stop_atr": 5.0, "sides": 1}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            c = df["close"]
            atr = ta.atr(df, 24)
            er = ta.efficiency_ratio(c, p["L"])
            rk = ta.rolling_rank(er, 4320)
            r = ta.ret(c, p["L"])
            ok = (rk >= p["q"]) & atr.notna()
            long = ok & (r > 0); short = ok & (r < 0)
            if p.get("sides", 0) == 1: short &= False
            if p.get("sides", 0) == -1: long &= False
            side = np.where(long, 1, np.where(short, -1, 0))
            it["side"] = side.astype(np.int8)
            it["stop"] = np.where(side > 0, c - p["stop_atr"] * atr, c + p["stop_atr"] * atr)
            out[sym] = it
        return out


class ImpulseCap(Impulse):
    """Impulse (with-trend only) but at most `cap` new entries per bar: the largest |bar move in ATRs| among the month's top-10."""
    name = "trend_impulse_cap"
    params = {"L": 336, "k": 2.5, "v": 3.0, "stop_atr": 3.0, "mode": 1, "cap": 3}

    def intents(self, data, p):
        base = super().intents(data, p)
        idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
        score = {}
        for sym, df in data.items():
            mv = ((df["close"] - df["open"]) / ta.atr(df, 24).shift(1)).abs()
            ok = (base[sym]["side"] != 0) & store.tradable_mask(sym, df.index)
            score[sym] = mv.where(ok)
        rk = pd.DataFrame(score).reindex(idx).rank(axis=1, ascending=False)
        for sym, it in base.items():
            keep = (rk[sym].reindex(it.index) <= p["cap"]).to_numpy()
            it["side"] = np.where(keep, it["side"], 0).astype(np.int8)
        return base
