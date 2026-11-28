"""Buy when open interest collapses during a sharp multi-hour drop; hold 12 hours."""
from __future__ import annotations

import numpy as np

from . import ta
from .base import Strategy
from .common import entries, mark_sigma, print_ok


class RevertOiWipe(Strategy):
    name = "revert_oi_wipe"
    idea = "Buy when open interest collapses during a 3-hour drop of more than 3 sigma, and hold 12 hours."
    cause = ("A collapse in open interest during a sharp drop means leveraged longs were forcibly closed, so the "
             "selling was mechanical and is finished.")
    loser = "Liquidated longs, and late shorts who sell into the hole the liquidations left."
    regime = "wild"
    valid_bars = 1
    max_hold = 12
    params = {"k": 3, "z": 3.0, "q": 0.01, "stop_atr": 4.0}
    grid = {"k": [1, 3, 6], "stop_atr": [3.0, 4.0, 5.0]}
    needs = ("oi", "mark_close")

    def intents(self, data, p):
        out = {}
        k = int(p["k"])
        for sym, df in data.items():
            mark = df["mark_close"]
            _, sig = mark_sigma(df)
            mz = np.log(mark / mark.shift(k)) / (sig * np.sqrt(k))
            oi = df["oi"].astype("float64")
            doi = oi / oi.shift(k) - 1.0
            thr = doi.rolling(720, min_periods=240).quantile(p["q"]).shift(1)
            long = (doi < thr) & (mz < -p["z"]) & print_ok(df) & oi.notna() & mark.notna()
            out[sym] = entries(df, long, None, p["stop_atr"] * ta.atr(df, 24))
        return out


STRATEGY = RevertOiWipe()
