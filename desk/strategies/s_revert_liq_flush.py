"""Buy after an hour with a liquidation spike and a -3 sigma bar; hold 12 hours."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import entries, mark_sigma, print_ok


class RevertLiqFlush(Strategy):
    name = "revert_liq_flush"
    idea = ("Buy after an hour that combines a liquidation-volume spike with a bar of -3 sigma or worse, and "
            "hold 12 hours.")
    cause = ("Forced liquidations sell at any price; once the forced flow is done the price recovers part of "
             "the move because no one chose to sell there.")
    loser = "Liquidated longs and momentum sellers who join at the low of a forced move."
    regime = "wild"
    valid_bars = 1
    max_hold = 12
    params = {"z": 3.0, "liq_mult": 2.0, "stop_atr": 4.0}
    grid = {"liq_mult": [1.5, 2.0, 3.0], "stop_atr": [3.0, 4.0, 5.0]}
    needs = ("liq_vol", "mark_close")

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            lr, sig = mark_sigma(df)
            mz1 = lr / sig
            liq_usd = df["liq_vol"].astype("float64") * df["close"]
            q99 = liq_usd.rolling(720, min_periods=240).quantile(0.99).shift(1)
            long = (liq_usd > p["liq_mult"] * q99) & (q99 > 0) & (mz1 < -p["z"]) & print_ok(df)
            out[sym] = entries(df, long, None, p["stop_atr"] * ta.atr(df, 24))
        return out


STRATEGY = RevertLiqFlush()
