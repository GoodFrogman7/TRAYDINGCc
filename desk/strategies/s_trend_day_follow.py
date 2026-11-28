"""Follow a big, high-volume day that extends the prior 14-day trend; hold up to a week."""
from __future__ import annotations

import numpy as np

from . import ta
from .base import Strategy
from .common import entries


class TrendDayFollow(Strategy):
    name = "trend_day_follow"
    idea = ("After a 24-hour move larger than 2 trailing standard deviations on more than twice normal 24-hour "
            "volume, in the direction of the prior 14-day trend, enter with the move and hold for up to a week.")
    cause = ("A high-volume day that extends an existing trend marks new information that slower holders take "
             "days to act on, so the move keeps going over the following week.")
    loser = ("Traders who fade the big day expecting a snap-back, and holders positioned against the trend who "
             "cover or sell over the following days.")
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "k": 2.0, "v": 2.0, "stop_atr": 5.0}
    grid = {"k": [2.0, 2.5], "stop_atr": [5.0, 7.0], "L": [168, 336]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            c = df["close"]
            r24 = c / c.shift(24) - 1.0
            sd = r24.rolling(720, min_periods=360).std().shift(24)
            v24 = df["volume"].rolling(24, min_periods=24).sum()
            vr = v24 / v24.shift(24).rolling(720, min_periods=360).mean()
            tr = np.sign(ta.ret(c, p["L"]).shift(24))          # trend measured before the impulse day
            atr = ta.atr(df, 24)
            long = (r24 > p["k"] * sd) & (vr > p["v"]) & (tr > 0)
            short = (r24 < -p["k"] * sd) & (vr > p["v"]) & (tr < 0)
            out[sym] = entries(df, long, short, p["stop_atr"] * atr)
        return out


STRATEGY = TrendDayFollow()
