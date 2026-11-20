"""After a breakdown in an already volatile market, rest a bid well below; take profit 2 ATR above the fill."""
from __future__ import annotations

import numpy as np

from . import ta
from .base import Strategy, blank_intents


class FlowHotBreakdownLimitFade(Strategy):
    name = "flow_hot_breakdown_limit_fade"
    idea = ("After a close below the 48-hour low while volatility is already expanded, rest a buy limit 1.5 ATR "
            "lower for three bars and take profit 2 ATR above the fill.")
    cause = ("A breakdown in an already volatile market triggers stops and liquidations that overshoot by more "
             "than an ATR, and a resting bid there is paid to supply liquidity to forced sellers.")
    loser = "Stop-loss and liquidation sellers who cross the spread at the worst moment of the flush."
    regime = "wild"
    valid_bars = 3
    max_hold = 12
    params = {"n": 48, "rank_min": 0.7, "limit_atr": 1.5, "stop_atr": 3.0, "tp_atr": 2.0}
    grid = {"n": [36, 48, 72], "rank_min": [0.5, 0.7, 0.85], "limit_atr": [1.0, 1.5, 2.0]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            c = df["close"]
            atr = ta.atr(df, 24)
            rank = ta.rolling_rank(ta.bb_width(c, 48, 2.0), 720).shift(1)
            sig = ((c < ta.donchian_low(df, int(p["n"]))) & (rank > p["rank_min"]) & atr.notna()).fillna(False)
            it = blank_intents(df.index)
            m = sig.to_numpy(dtype=bool)
            limit = (c - p["limit_atr"] * atr).to_numpy()
            a = atr.to_numpy()
            it["side"] = m.astype(np.int8)
            it["limit"] = np.where(m, limit, np.nan)
            it["stop"] = np.where(m, limit - p["stop_atr"] * a, np.nan)
            it["tp"] = np.where(m, limit + p["tp_atr"] * a, np.nan)
            out[sym] = it
        return out


STRATEGY = FlowHotBreakdownLimitFade()
