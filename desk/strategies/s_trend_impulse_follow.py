"""Follow one violent high-volume hour in the direction of the 14-day trend; hold up to three days."""
from __future__ import annotations

import numpy as np

from . import ta
from .base import Strategy
from .common import entries


class TrendImpulseFollow(Strategy):
    name = "trend_impulse_follow"
    idea = ("After one hourly bar that moves more than 2.5 ATR on more than 3 times normal volume in the "
            "direction of the 14-day trend, enter with it and hold up to three days.")
    cause = ("A violent high-volume hour in the direction of the trend is a forced or informed repricing that "
             "the rest of the market finishes over the next few days.")
    loser = "Traders who fade the spike at market, and stops and liquidations of those leaning against the trend."
    regime = "trending"
    valid_bars = 1
    max_hold = 72
    params = {"L": 336, "k": 2.5, "v": 3.0, "stop_atr": 3.0}
    grid = {"k": [2.0, 2.5, 3.0], "v": [2.0, 3.0, 4.0], "stop_atr": [3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            atr = ta.atr(df, 24)
            mv = (df["close"] - df["open"]) / atr.shift(1)
            volr = df["volume"] / ta.sma(df["volume"], 168).shift(1)
            tr = np.sign(ta.ret(df["close"], p["L"]).shift(1))
            long = (mv > p["k"]) & (volr > p["v"]) & (tr > 0)
            short = (mv < -p["k"]) & (volr > p["v"]) & (tr < 0)
            out[sym] = entries(df, long, short, p["stop_atr"] * atr)
        return out


STRATEGY = TrendImpulseFollow()
