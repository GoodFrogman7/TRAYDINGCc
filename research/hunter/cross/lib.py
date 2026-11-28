"""Shared helpers for the cross-market lens. DESIGN WINDOW ONLY (store.load_design)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from desk.data import store

BTC, ETH = "PF_XBTUSD", "PF_ETHUSD"


def panels():
    """Wide panels on a common hourly index. Row t is known at the close of bar t."""
    data = store.load_design()
    idx = pd.date_range(min(d.index[0] for d in data.values()),
                        max(d.index[-1] for d in data.values()), freq="h", name="time")
    P = {}
    for col in ["open", "high", "low", "close", "volume", "funding", "liq_vol", "oi", "premium",
                "buy_vol", "sell_vol", "bid_10k", "ask_10k"]:
        P[col] = pd.DataFrame({s: d[col].reindex(idx) for s, d in data.items()})
    miss = pd.DataFrame({s: d["bar_missing"].astype(bool).reindex(idx) for s, d in data.items()})
    P["missing"] = miss.fillna(True).astype(bool)
    trad = pd.DataFrame({s: store.tradable_mask(s, idx) for s in data})
    P["trad"] = trad & P["close"].notna() & ~P["missing"]
    return data, P


def fwd_from_next_open(O: pd.DataFrame, h: int, delay: int = 0) -> pd.DataFrame:
    """Return from open[t+1+delay] to open[t+1+delay+h] (signal at close of t)."""
    a = O.shift(-(1 + delay))
    b = O.shift(-(1 + delay + h))
    return b / a - 1.0


def stats(r: pd.Series, label: str = "", by_day: bool = True) -> dict:
    """r: series of signed forward returns indexed by event time (may repeat times).
    t_day = t-stat of the per-UTC-day mean (clusters same-day events)."""
    r = r.dropna()
    n = len(r)
    if n < 5:
        return dict(label=label, n=n)
    m, md, hit = r.mean(), r.median(), (r > 0).mean()
    t = m / (r.std(ddof=1) / np.sqrt(n)) if r.std() > 0 else np.nan
    out = dict(label=label, n=n, mean_bps=round(m * 1e4, 1), med_bps=round(md * 1e4, 1),
               hit=round(hit, 3), t=round(t, 2))
    if by_day:
        g = r.groupby(r.index.floor("D")).mean()
        if len(g) > 3 and g.std() > 0:
            out["n_days"] = len(g)
            out["t_day"] = round(g.mean() / (g.std(ddof=1) / np.sqrt(len(g))), 2)
    return out


def by_year(r: pd.Series) -> dict:
    r = r.dropna()
    out = {}
    for y, g in r.groupby(r.index.year):
        out[int(y)] = (len(g), round(g.mean() * 1e4, 1), round((g > 0).mean(), 2))
    return out


def stack_events(sig: pd.DataFrame, fwd: pd.DataFrame, trad: pd.DataFrame, sign: pd.DataFrame | int = 1) -> pd.Series:
    """Collect sign*fwd on bars where sig is True and the symbol is tradable. Index = event time."""
    m = (sig & trad).to_numpy()
    f = fwd.to_numpy()
    if isinstance(sign, pd.DataFrame):
        f = f * sign.to_numpy()
    else:
        f = f * sign
    rows, cols = np.nonzero(m)
    return pd.Series(f[rows, cols], index=sig.index[rows])


def show(rows: list[dict]) -> None:
    print(pd.DataFrame(rows).to_string(index=False))
