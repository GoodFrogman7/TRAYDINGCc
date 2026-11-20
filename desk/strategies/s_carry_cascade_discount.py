"""Buy a perp trading unusually far below its index, only during a market-wide discount."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import store
from . import ta
from .base import Strategy
from .common import entries, month_code, months_where, premium_z


class CarryCascadeDiscount(Strategy):
    name = "carry_cascade_discount"
    idea = ("Buy a perp that trades unusually far below its index, but only when at least two of the tradable "
            "top-10 perps are at an unusual discount at the same time (a market-wide leverage flush, not "
            "coin-specific news).")
    cause = ("Cross-margined longs are liquidated at market in a cascade, pushing perps below index and price "
             "below where unforced sellers would trade; once the forced flow ends the gap closes and price rebounds.")
    loser = "Over-leveraged longs being liquidated at market and late momentum shorts who sell the perp below index."
    regime = "wild"
    valid_bars = 1
    max_hold = 36
    params = {"pm_n": 8, "norm_n": 720, "z": 2.0, "zb": 2.0, "k": 2, "atr_n": 24, "stop_atr": 3.0}
    grid = {"z": [1.5, 2.0, 2.5], "k": [2, 3], "stop_atr": [2.5, 3.0, 4.0]}
    needs = ("premium",)

    def intents(self, data, p):
        lo = min(df.index[0] for df in data.values())
        hi = max(df.index[-1] for df in data.values())
        union = pd.date_range(lo, hi, freq="h", name="time")
        in_months = months_where(store.universe(), lambda syms: syms)     # ranked on the prior 30 days
        pz = {s: premium_z(df, int(p["pm_n"]), int(p["norm_n"])) for s, df in data.items()}
        breadth = np.zeros(len(union))
        for s, df in data.items():
            member = np.isin(month_code(df.index), in_months.get(s, []))
            flag = (pz[s][1] <= -p["zb"]).to_numpy(dtype=bool) & member & ~df["bar_missing"].to_numpy(dtype=bool)
            breadth += pd.Series(flag.astype(float), index=df.index).reindex(union, fill_value=0.0).to_numpy()
        breadth = pd.Series(breadth, index=union)
        out = {}
        for s, df in data.items():
            pm, z = pz[s]
            long = (z <= -p["z"]) & (pm < 0) & (breadth.reindex(df.index) >= p["k"])
            out[s] = entries(df, long, None, p["stop_atr"] * ta.atr(df, int(p["atr_n"])))
        return out


STRATEGY = CarryCascadeDiscount()
