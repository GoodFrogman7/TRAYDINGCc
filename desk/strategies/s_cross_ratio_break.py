"""When an alt's price ratio to BTC breaks its 14-day range, trade the alt that way, with BTC's trend."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import BTC, daily_vol, entries


class CrossRatioBreak(Strategy):
    name = "cross_ratio_break"
    idea = ("When an alt's price ratio to BTC breaks its 14-day range, trade the alt in that direction for up "
            "to a week, long only when BTC is above its 20-day average and short only when below.")
    cause = ("A coin breaking out against BTC is being repriced on its own flow, and relative repricings last "
             "days because holders rebalance between coins slowly.")
    loser = "Pair traders fading the ratio back to its range, and holders slow to rotate out of the weak coin."
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"N": 336, "btc_ma": 480, "stop_k": 2.5, "refractory": 48}
    grid = {"N": [168, 336, 504], "stop_k": [2.0, 2.5, 3.0]}

    def intents(self, data, p):
        out = {}
        N, ref = int(p["N"]), int(p["refractory"])
        btc = data.get(BTC)
        if btc is not None:
            btc_c = btc["close"]
            btc_up = btc_c > ta.sma(btc_c, int(p["btc_ma"]))
            btc_dn = btc_c < ta.sma(btc_c, int(p["btc_ma"]))
        for sym, df in data.items():
            c = df["close"]
            dist = c * p["stop_k"] * daily_vol(c)
            if btc is None or sym == BTC:
                out[sym] = entries(df, None, None, dist)
                continue
            ratio = c / btc_c.reindex(df.index)
            up = (ratio > ratio.shift(1).rolling(N, min_periods=N).max()).astype(float)
            dn = (ratio < ratio.shift(1).rolling(N, min_periods=N).min()).astype(float)
            first_up = (up > 0) & (up.shift(1).rolling(ref, min_periods=ref).sum() == 0)
            first_dn = (dn > 0) & (dn.shift(1).rolling(ref, min_periods=ref).sum() == 0)
            long = first_up & btc_up.reindex(df.index).fillna(False)
            short = first_dn & btc_dn.reindex(df.index).fillna(False)
            out[sym] = entries(df, long, short, dist)
        return out


STRATEGY = CrossRatioBreak()
