"""REFERENCE ONLY (not registered): shows the strategy contract end to end.

Long-only channel breakout with a volatility stop. Use it as the template for
real strategies (modules named s_<id>.py exposing STRATEGY).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import ta
from .base import Strategy, blank_intents


class RefDonchian(Strategy):
    name = "ref_donchian"
    idea = "Buy a close above the prior N-bar high and trail a volatility stop."
    cause = "Trends persist because large holders build positions over days, not minutes."
    loser = "Traders fading the breakout and late shorts forced to cover."
    regime = "trending"
    valid_bars = 1
    max_hold = 0
    params = {"n": 96, "atr_n": 24, "stop_atr": 3.0}
    grid = {"n": [72, 96, 120], "stop_atr": [2.5, 3.0, 3.5]}

    def intents(self, data: dict[str, pd.DataFrame], p: dict) -> dict[str, pd.DataFrame]:
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            atr = ta.atr(df, p["atr_n"])
            hi = ta.donchian_high(df, p["n"])            # excludes the current bar
            brk = (df["close"] > hi) & atr.notna()
            it["side"] = np.where(brk, 1, 0).astype(np.int8)
            it["stop"] = df["close"] - p["stop_atr"] * atr   # market entry at next open, stop attached
            it["trail"] = df["close"] - p["stop_atr"] * atr  # engine only ever tightens
            out[sym] = it
        return out


STRATEGY = RefDonchian()
