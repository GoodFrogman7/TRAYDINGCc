"""Trade BTC and ETH for 24 hours in the direction BTC moved over the weekend."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import ta
from .base import Strategy
from .common import BTC, ETH, entries, is_weekly_bar


class CrossWeekendFollowMajors(Strategy):
    name = "cross_weekend_follow_majors"
    idea = ("Trade BTC and ETH for 24 hours in the direction BTC moved over the weekend, entering at the "
            "Sunday 22:00 UTC open.")
    cause = ("Weekend moves happen without institutional desks; when they return on Monday they trade in the "
             "direction the weekend already revealed instead of fading it.")
    loser = "Weekend traders who fade the move expecting Monday to reverse it."
    regime = "trending"
    valid_bars = 1
    max_hold = 24
    params = {"look": 48, "thr": 0.005, "stop_atr": 4.0, "sig_dow": 6, "sig_hour": 21}
    grid = {"thr": [0.0, 0.005, 0.01], "stop_atr": [3.0, 4.0, 5.0]}

    def intents(self, data, p):
        out = {}
        btc = data.get(BTC)
        w_btc = None if btc is None else btc["close"] / btc["close"].shift(int(p["look"])) - 1.0
        for sym, df in data.items():
            atr = ta.atr(df, 24)
            if w_btc is None or sym not in (BTC, ETH):
                out[sym] = entries(df, None, None, atr)
                continue
            w = w_btc.reindex(df.index)
            on = pd.Series(is_weekly_bar(df.index, int(p["sig_dow"]), int(p["sig_hour"])), index=df.index)
            go = on & (w.abs() >= p["thr"])
            out[sym] = entries(df, go & (np.sign(w) > 0), go & (np.sign(w) < 0), p["stop_atr"] * atr)
        return out


STRATEGY = CrossWeekendFollowMajors()
