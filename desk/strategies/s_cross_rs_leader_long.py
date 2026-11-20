"""Once a day, buy the two strongest coins of the month's top 10 while the market is broadly healthy."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import store
from .base import Strategy, blank_intents
from .common import daily_vol, month_code, months_where


class CrossRsLeaderLong(Strategy):
    name = "cross_rs_leader_long"
    idea = ("Once a day, buy the two strongest coins of the month's top 10 on 14-day return, only while at "
            "least half the top 10 trade above their 200-hour average, and hold up to a week.")
    cause = ("Capital rotates slowly into the coins already leading, because allocators chase recent relative "
             "performance and leaders attract the marginal buyer while the market is healthy.")
    loser = "Holders of laggards waiting for mean reversion, and shorts fading the leaders."
    regime = "trending"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "top": 2, "stop_k": 2.0, "exit_rank": 5, "breadth_min": 0.5, "breadth_ma": 200}
    grid = {"L": [168, 336, 504], "stop_k": [1.5, 2.0, 3.0]}

    def intents(self, data, p):
        L = int(p["L"])
        lo = min(df.index[0] for df in data.values())
        hi = max(df.index[-1] for df in data.values())
        idx = pd.date_range(lo, hi, freq="h", name="time")
        close = pd.DataFrame({s: df["close"].reindex(idx) for s, df in data.items()})
        uni = store.universe()                       # ranked on the 30 days before each month
        in_months = months_where(uni, lambda syms: syms)
        code = month_code(idx)
        member = pd.DataFrame({s: np.isin(code, in_months.get(s, [])) for s in close.columns}, index=idx)
        mom = close / close.shift(L) - 1.0
        valid = member & mom.notna()
        rank = mom.where(valid).rank(axis=1, ascending=False)
        enough = valid.sum(axis=1) >= 8
        sma = close.rolling(int(p["breadth_ma"]), min_periods=int(p["breadth_ma"])).mean()
        have = member & sma.notna() & close.notna()
        breadth = ((close > sma) & have).sum(axis=1) / have.sum(axis=1).replace(0, np.nan)
        decide = pd.Series(idx.hour == 23, index=idx) & enough
        buy = (rank <= p["top"]) & (mom > 0)
        buy = buy.mul(decide & (breadth >= p["breadth_min"]), axis=0)
        leave = (valid & (rank > p["exit_rank"])).mul(decide, axis=0)
        out = {}
        for sym, df in data.items():
            it = blank_intents(df.index)
            stop = df["close"] * (1.0 - p["stop_k"] * daily_vol(df["close"]))
            m = buy[sym].reindex(df.index).fillna(False).to_numpy(dtype=bool) & stop.notna().to_numpy() & \
                (stop > 0).to_numpy()
            it["side"] = m.astype(np.int8)
            it["stop"] = np.where(m, stop.to_numpy(), np.nan)
            it["exit"] = leave[sym].reindex(df.index).fillna(False).to_numpy(dtype=bool)
            out[sym] = it
        return out


STRATEGY = CrossRsLeaderLong()
