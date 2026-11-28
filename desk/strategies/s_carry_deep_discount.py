"""Buy the first hour a perp's 8-hour average premium is deeply and unusually below its index."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import entries, first_in, premium_z


class CarryDeepDiscount(Strategy):
    name = "carry_deep_discount"
    idea = ("Buy the first hour a perp's 8h average premium is both 2 standard deviations below its own 30-day "
            "norm and at least 5 bps below index.")
    cause = ("A sustained perp discount means sellers are paying up to get out through the perp (liquidations, "
             "panic hedging) while longs are paid funding, and the gap closes when the forced flow stops.")
    loser = "Forced and panicked perp sellers who accept a price below the spot index."
    regime = "wild"
    valid_bars = 1
    max_hold = 36
    params = {"pm_n": 8, "norm_n": 720, "z": 2.0, "floor_bp": 5.0, "cool": 24, "atr_n": 24, "stop_atr": 3.0}
    grid = {"z": [2.0, 2.5, 3.0], "stop_atr": [2.5, 3.0, 4.0]}
    needs = ("premium",)

    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            pm, z = premium_z(df, int(p["pm_n"]), int(p["norm_n"]))
            atr = ta.atr(df, int(p["atr_n"]))
            raw = (z <= -p["z"]) & (pm <= -p["floor_bp"] / 1e4) & atr.notna()
            out[s] = entries(df, first_in(raw, int(p["cool"])), None, p["stop_atr"] * atr)
        return out


STRATEGY = CarryDeepDiscount()
