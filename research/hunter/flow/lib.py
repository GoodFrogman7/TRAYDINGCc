"""Shared helpers for the flow-lens event studies. Design window only."""
from __future__ import annotations
import numpy as np
import pandas as pd
from desk.data import store
from desk.strategies import ta

MAJ = {"PF_XBTUSD", "PF_ETHUSD"}


def load():
    data = store.load_design()
    out = {}
    for s, df in data.items():
        df = df.copy()
        df["tradable"] = store.tradable_mask(s, df.index).values
        out[s] = df
    return out


def fwd(df: pd.DataFrame, h: int, delay: int = 0) -> pd.Series:
    """Return from open of bar t+1+delay to open of bar t+1+delay+h (h bars held)."""
    o = df["open"]
    ent = o.shift(-(1 + delay))
    ext = o.shift(-(1 + delay + h))
    return ext / ent - 1.0


def stats(r: pd.Series, label: str = "") -> dict:
    r = r.dropna()
    n = len(r)
    if n == 0:
        return dict(label=label, n=0, mean=np.nan, med=np.nan, hit=np.nan, t=np.nan)
    m = r.mean()
    sd = r.std(ddof=1) if n > 1 else np.nan
    t = m / (sd / np.sqrt(n)) if n > 1 and sd > 0 else np.nan
    return dict(label=label, n=n, mean=round(m * 1e4, 1), med=round(r.median() * 1e4, 1),
                hit=round((r > 0).mean(), 3), t=round(t, 2))


def dedupe(sig: pd.Series, gap: int) -> pd.Series:
    """Keep a True only if no kept True in the previous `gap` bars (causal)."""
    v = sig.fillna(False).values.astype(bool)
    out = np.zeros(len(v), dtype=bool)
    last = -10**9
    for i in np.nonzero(v)[0]:
        if i - last > gap:
            out[i] = True
            last = i
    return pd.Series(out, index=sig.index)


def study(events: pd.DataFrame, cols=("r",), by=("year", "side")) -> pd.DataFrame:
    rows = []
    for c in cols:
        rows.append(stats(events[c], f"{c}|all"))
        for b in by:
            for k, g in events.groupby(b):
                rows.append(stats(g[c], f"{c}|{b}={k}"))
    return pd.DataFrame(rows)


def cluster_t(events: pd.DataFrame, col: str = "r") -> float:
    """t-stat on daily-clustered means (events on the same UTC day are not independent)."""
    e = events.dropna(subset=[col])
    d = e.groupby(e["time"].dt.floor("D"))[col].mean()
    if len(d) < 3:
        return np.nan
    return round(d.mean() / (d.std(ddof=1) / np.sqrt(len(d))), 2)
