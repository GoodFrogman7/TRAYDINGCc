"""Buy a sharp 4-hour drop only when the order book has thinned out; hold 24 hours."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import entries


class FlowLiquidityVacuumFade(Strategy):
    name = "flow_liquidity_vacuum_fade"
    idea = ("Buy a 4-hour drop of more than 2 ATR only when the $10k order-book spread has blown out to at "
            "least 3x its normal level, and hold 24 hours.")
    cause = ("When market makers pull quotes the price falls through an empty book further than the selling "
             "justifies, and it retraces when quotes return.")
    loser = "Stop-market and liquidation sellers who paid for immediacy in an empty book."
    regime = "wild"
    valid_bars = 1
    max_hold = 24
    params = {"sp_mult": 3.0, "drop_atr": 2.0, "stop_pct": 0.08}
    grid = {"sp_mult": [2.5, 3.0, 4.0], "drop_atr": [1.5, 2.0, 2.5], "stop_pct": [0.06, 0.08, 0.10]}
    needs = ("bid_10k", "ask_10k")

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            c = df["close"]
            half = (df["ask_10k"] - df["bid_10k"]) / (df["ask_10k"] + df["bid_10k"])
            half = half.where(half > 0)
            rel = half / half.rolling(168, min_periods=48).median().shift(1)
            atr = ta.atr(df, 24)
            long = (rel >= p["sp_mult"]) & ((c.shift(4) - c) > p["drop_atr"] * atr) & atr.notna()
            out[sym] = entries(df, long, None, c * p["stop_pct"])      # fixed-percentage disaster stop
        return out


STRATEGY = FlowLiquidityVacuumFade()
