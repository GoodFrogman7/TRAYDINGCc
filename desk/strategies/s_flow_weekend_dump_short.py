"""If the thin weekend closed sharply down, short into Monday for 24 hours."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import ta
from .base import Strategy
from .common import entries, is_weekly_bar


class FlowWeekendDumpShort(Strategy):
    name = "flow_weekend_dump_short"
    idea = ("If the thin-liquidity weekend (Fri 22:00 to Sun 22:00 UTC) closed sharply down, short at the Sunday "
            "22:00 UTC open and hold 24 hours into the Monday session.")
    cause = ("A weekend sell-off happens in thin books without institutional flow, so the de-risking, margin "
             "calls and liquidations it triggers only arrive when weekday liquidity returns on Monday.")
    loser = "Weekend dip-buyers and leveraged longs who get liquidated into the Monday open."
    regime = "wild"
    valid_bars = 1
    max_hold = 24
    params = {"z": 0.75, "hour": 21, "stop_atr": 3.0}
    grid = {"z": [0.5, 0.75, 1.0], "hour": [19, 21, 23], "stop_atr": [2.5, 3.0, 3.5]}

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            c = df["close"]
            r = c / c.shift(1) - 1.0
            sd = r.rolling(168, min_periods=100).std().shift(1)
            z48 = (c / c.shift(48) - 1.0) / (sd * np.sqrt(48))
            on = pd.Series(is_weekly_bar(df.index, 6, int(p["hour"])), index=df.index)
            out[sym] = entries(df, None, on & (z48 <= -p["z"]), p["stop_atr"] * ta.atr(df, 24))
        return out


STRATEGY = FlowWeekendDumpShort()
