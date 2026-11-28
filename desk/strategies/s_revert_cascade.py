"""Buy a coin down hard over 6 hours while bitcoin is also down hard; hold 12 hours."""
from __future__ import annotations

import numpy as np

from . import ta
from .base import Strategy
from .common import BTC, entries, mark_sigma, print_ok


def _mz(df, k: int):
    _, sig = mark_sigma(df)
    return np.log(df["mark_close"] / df["mark_close"].shift(k)) / (sig * np.sqrt(k))


class RevertCascade(Strategy):
    name = "revert_cascade"
    idea = ("Buy a coin that is down more than 4.5 sigma over 6 hours when bitcoin is also down more than 3 "
            "sigma over the same 6 hours, and hold 12 hours.")
    cause = ("A market-wide cascade forces sales of everything at once, pushing individual coins further than "
             "their own news justifies, and they rebound when the forced selling stops.")
    loser = "Forced sellers across the market and traders who short the last leg of a cascade."
    regime = "wild"
    valid_bars = 1
    max_hold = 12
    params = {"k": 6, "z": 4.5, "zb": 3.0, "stop_atr": 4.0}
    grid = {"z": [4.0, 4.5, 5.0], "zb": [2.0, 3.0, 4.0]}
    needs = ("mark_close",)

    def intents(self, data, p):
        k = int(p["k"])
        btc6 = _mz(data[BTC], k) if BTC in data else None
        out = {}
        for sym, df in data.items():
            if btc6 is None:
                out[sym] = entries(df, None, None, ta.atr(df, 24))
                continue
            long = (_mz(df, k) < -p["z"]) & (btc6.reindex(df.index) < -p["zb"]) & print_ok(df)
            out[sym] = entries(df, long, None, p["stop_atr"] * ta.atr(df, 24))
        return out


STRATEGY = RevertCascade()
