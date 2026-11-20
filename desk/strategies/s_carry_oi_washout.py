"""Buy the first new 72-hour closing low that comes with open interest collapsing."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import entries, first_in


class CarryOiWashout(Strategy):
    name = "carry_oi_washout"
    idea = "Buy the first new 72-hour closing low that comes with open interest down 15% or more in 24 hours."
    cause = ("A new low on collapsing open interest is positions being closed or liquidated rather than new "
             "shorts being opened, so the selling is exhaustible and stops when the leverage is gone.")
    loser = "Leveraged longs closed out at the low and traders who short the breakdown after the fuel is spent."
    regime = "wild"
    valid_bars = 1
    max_hold = 36
    params = {"don_n": 72, "oi_n": 24, "oi_drop": 0.15, "cool": 24, "atr_n": 24, "stop_atr": 3.0}
    grid = {"oi_drop": [0.10, 0.15, 0.20], "don_n": [48, 72, 96]}
    needs = ("oi",)

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            oi = df["oi"].astype("float64")
            d = oi / oi.shift(int(p["oi_n"])) - 1.0
            atr = ta.atr(df, int(p["atr_n"]))
            raw = (df["close"] < ta.donchian_low(df, int(p["don_n"]))) & (d <= -p["oi_drop"]) & atr.notna() & oi.notna()
            out[s] = entries(df, first_in(raw, int(p["cool"])), None, p["stop_atr"] * atr)
        return out


STRATEGY = CarryOiWashout()
