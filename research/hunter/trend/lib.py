"""Hunter / trend lens: shared helpers. DESIGN WINDOW ONLY (store.load_design)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.data import store  # noqa: E402
from desk.strategies import ta  # noqa: E402

BTC = "PF_XBTUSD"
MAJORS = ("PF_XBTUSD", "PF_ETHUSD")
_CACHE: dict = {}


def load() -> dict[str, pd.DataFrame]:
    """Design-window bars, with the tradable mask attached as column `trd`."""
    if "data" not in _CACHE:
        data = store.load_design()
        for s, df in data.items():
            df["trd"] = store.tradable_mask(s, df.index).to_numpy() & ~df["bar_missing"].astype(bool).to_numpy()
        _CACHE["data"] = data
    return _CACHE["data"]


def fwd(df: pd.DataFrame, h: int, delay: int = 0) -> pd.Series:
    """Return from the open of bar t+1+delay to the open of bar t+1+delay+h (signal at close of t).
    Uses shift(-n) ONLY to build the outcome variable, never a feature."""
    o = df["open"]
    return o.shift(-(1 + delay + h)) / o.shift(-(1 + delay)) - 1.0


def dedupe(sig: pd.Series, gap: int) -> pd.Series:
    """Keep an event only if there was no kept event in the previous `gap` bars (same symbol)."""
    v = sig.to_numpy().astype(bool)
    out = np.zeros(len(v), dtype=bool)
    last = -10**9
    for i in np.nonzero(v)[0]:
        if i - last >= gap:
            out[i] = True
            last = i
    return pd.Series(out, index=sig.index)


def stats(r: pd.Series) -> dict:
    """r: signed forward returns indexed by event time (may contain several symbols)."""
    r = r.dropna()
    n = len(r)
    if n < 5:
        return dict(n=n, mean=np.nan, med=np.nan, hit=np.nan, t=np.nan, t_day=np.nan)
    m, s = r.mean(), r.std()
    # day-clustered t: collapse to one observation per calendar day (alts move together)
    d = r.groupby(r.index.floor("D")).mean()
    td = d.mean() / d.std() * np.sqrt(len(d)) if len(d) > 3 and d.std() > 0 else np.nan
    return dict(n=n, mean=round(m * 1e4, 1), med=round(r.median() * 1e4, 1), hit=round((r > 0).mean(), 3),
                t=round(m / s * np.sqrt(n), 2) if s > 0 else np.nan, t_day=round(td, 2))


def collect(sigfn, h: int, delay: int = 0, gap: int | None = None, syms=None) -> pd.DataFrame:
    """sigfn(sym, df, data) -> Series of side in {-1,0,+1} decided at the close of bar t.
    Returns one row per event: time, sym, side, signed fwd return over h bars (entry next open)."""
    data = load()
    rows = []
    for s, df in data.items():
        if syms is not None and s not in syms:
            continue
        if not df["trd"].any():
            continue
        side = sigfn(s, df, data)
        if side is None:
            continue
        side = side.reindex(df.index).fillna(0)
        f = fwd(df, h, delay)
        for sd in (1, -1):
            ev = (side == sd) & df["trd"]
            ev = dedupe(ev, gap if gap is not None else h)
            idx = ev[ev].index
            if len(idx):
                rows.append(pd.DataFrame({"sym": s, "side": sd, "r": sd * f.loc[idx].to_numpy()}, index=idx))
    if not rows:
        return pd.DataFrame(columns=["sym", "side", "r"])
    return pd.concat(rows).sort_index()


def report(ev: pd.DataFrame, label: str = "") -> pd.DataFrame:
    """All / long / short / by year / majors vs alts."""
    out = {}
    out["all"] = stats(ev["r"])
    out["long"] = stats(ev.loc[ev.side == 1, "r"])
    out["short"] = stats(ev.loc[ev.side == -1, "r"])
    for y in (2022, 2023, 2024):
        out[str(y)] = stats(ev.loc[ev.index.year == y, "r"])
    out["majors"] = stats(ev.loc[ev.sym.isin(MAJORS), "r"])
    out["alts"] = stats(ev.loc[~ev.sym.isin(MAJORS), "r"])
    t = pd.DataFrame(out).T
    if label:
        t.index.name = label
    return t


def btc_series(col: str = "close") -> pd.Series:
    return load()[BTC][col]


def align_btc(x: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """A BTC-derived (causal) feature on another symbol's index. ffill only."""
    return x.reindex(index).ffill()
