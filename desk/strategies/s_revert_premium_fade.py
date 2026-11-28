"""Fade an extreme perp-vs-index premium; exit when it normalises or after 8 hours."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import entries, print_ok


class RevertPremiumFade(Strategy):
    name = "revert_premium_fade"
    idea = ("Fade the perp when its hour-average premium to the spot index is extreme: short above +0.3%, long "
            "below -0.3%, and get out when the premium is back inside 0.1% or after 8 hours.")
    cause = ("A perp trading far from its index is being pushed by one-sided leveraged flow, and arbitrage plus "
             "funding pull it back to the index within hours.")
    loser = "Leveraged traders chasing the move on the perp at a price the spot market does not confirm."
    regime = "wild"
    valid_bars = 1
    max_hold = 8
    params = {"prem": 0.003, "stop_atr": 3.0, "exit_prem": 0.001, "atr_n": 24, "print_tol": 0.003}
    grid = {"prem": [0.0025, 0.003, 0.004], "stop_atr": [2.0, 3.0, 4.0]}
    needs = ("premium", "mark_close")

    def intents(self, data, p):
        out = {}
        for sym, df in data.items():
            prem = df["premium"].astype("float64")
            ok = print_ok(df, p["print_tol"]) & prem.notna() & df["mark_close"].notna()
            it = entries(df, (prem < -p["prem"]) & ok, (prem > p["prem"]) & ok, p["stop_atr"] * ta.atr(df, p["atr_n"]))
            it["exit"] = (prem.abs() < p["exit_prem"]).fillna(False).to_numpy()
            out[sym] = it
        return out


STRATEGY = RevertPremiumFade()
