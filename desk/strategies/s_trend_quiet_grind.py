"""Buy an unusually smooth 14-day rise; hold up to a week. Long only."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import entries


class TrendQuietGrind(Strategy):
    name = "trend_quiet_grind"
    idea = ("Buy a coin whose 14-day rise has been unusually smooth (efficiency ratio in the top 20% of its own "
            "last 180 days) and hold up to a week; long only.")
    cause = ("A two-week rise with very little back-and-forth is a patient buyer working a large order, and "
             "that buying is usually not finished when the pattern becomes visible.")
    loser = "Short sellers and early profit-takers who fade a slow grind because it has gone far without a blow-off."
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "q": 0.8, "stop_atr": 5.0}
    grid = {"q": [0.7, 0.8, 0.9], "stop_atr": [5.0, 7.0]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            c = df["close"]
            er = ta.efficiency_ratio(c, p["L"])
            rk = ta.rolling_rank(er, 4320)
            long = (rk >= p["q"]) & (ta.ret(c, p["L"]) > 0)
            out[sym] = entries(df, long, None, p["stop_atr"] * ta.atr(df, 24))
        return out


STRATEGY = TrendQuietGrind()
