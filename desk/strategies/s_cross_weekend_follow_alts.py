"""After a BTC weekend move, trade the month's most liquid alts that agree with it, for 24 hours."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import store
from . import ta
from .base import Strategy
from .common import BTC, ETH, entries, is_weekly_bar


class CrossWeekendFollowAlts(Strategy):
    name = "cross_weekend_follow_alts"
    idea = ("After the same weekend signal, trade the three highest-volume alts of the month for 24 hours in "
            "BTC's weekend direction, but only those whose own weekend move agrees with BTC's.")
    cause = ("Alts carry the market's weekend direction into Monday with more leverage than the majors, and "
             "those already moving with BTC have no coin-specific flow opposing it.")
    loser = "Weekend traders fading the move in alts, and holders of alts on the wrong side when Monday desks arrive."
    regime = "trending"
    valid_bars = 1
    max_hold = 24
    params = {"look": 48, "thr": 0.005, "stop_atr": 5.0, "n_alt": 3}
    grid = {"thr": [0.0, 0.005, 0.01], "stop_atr": [4.0, 5.0, 6.0], "n_alt": [2, 3, 5]}

    def intents(self, data, p):
        out = {}
        look, n_alt = int(p["look"]), int(p["n_alt"])
        btc = data.get(BTC)
        w_btc = None if btc is None else btc["close"] / btc["close"].shift(look) - 1.0
        # point-in-time: each month's list was ranked on the 30 days BEFORE that month
        cands = {m: set([s for s in syms if s not in (BTC, ETH)][:n_alt]) for m, syms in store.universe().items()}
        for sym, df in data.items():
            atr = ta.atr(df, 24)
            if w_btc is None or sym in (BTC, ETH):
                out[sym] = entries(df, None, None, atr)
                continue
            w = w_btc.reindex(df.index)
            own = df["close"] / df["close"].shift(look) - 1.0
            is_cand = pd.Series([sym in cands.get(m, ()) for m in df.index.strftime("%Y-%m")], index=df.index)
            on = pd.Series(is_weekly_bar(df.index, 6, 21), index=df.index)
            go = on & is_cand & (w.abs() >= p["thr"]) & (np.sign(own) == np.sign(w))
            out[sym] = entries(df, go & (w > 0), go & (w < 0), p["stop_atr"] * atr)
        return out


STRATEGY = CrossWeekendFollowAlts()
