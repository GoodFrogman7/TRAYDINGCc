"""Shared helpers for the mean-reversion event studies (design window only).

Conventions
-----------
* signal is decided at the close of bar t (row t), entry is the OPEN of bar t+1
* fwd_h   = open[t+1+h] / open[t+1] - 1          (hold h bars, exit at an open)
* fwd_h_d = open[t+2+h] / open[t+2] - 1          (entry delayed one more bar)
* all features are trailing (rolling / ewm / shift(+n)); the only negative
  shifts in this file build the forward-return LABELS.
* events are counted only where store.tradable_mask is True.
"""
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

HORIZONS = (1, 2, 4, 8, 12, 24, 48)
MAJORS = ("PF_XBTUSD", "PF_ETHUSD")


def load() -> dict[str, pd.DataFrame]:
    return store.load_design()


def add_labels(df: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """Forward returns from the next bar's open. LABELS ONLY (uses the future)."""
    o = df["open"]
    e1 = o.shift(-1)
    e2 = o.shift(-2)
    out = {}
    for h in horizons:
        out[f"fwd_{h}"] = o.shift(-(1 + h)) / e1 - 1.0
        out[f"fwd_{h}_d"] = o.shift(-(2 + h)) / e2 - 1.0
    # path extremes over the next H bars measured from the entry open (for stop studies)
    for h in (4, 8, 12, 24, 48):
        lo = df["low"].shift(-1)[::-1].rolling(h, min_periods=h).min()[::-1]
        hi = df["high"].shift(-1)[::-1].rolling(h, min_periods=h).max()[::-1]
        out[f"mae_lo_{h}"] = lo / e1 - 1.0     # worst low of bars t+1..t+h vs entry
        out[f"mfe_hi_{h}"] = hi / e1 - 1.0     # best high of bars t+1..t+h vs entry
    return pd.DataFrame(out, index=df.index)


def base_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    lr = np.log(c).diff()
    f["ret1"] = c / c.shift(1) - 1.0
    f["body"] = c / o - 1.0
    f["sig24"] = lr.rolling(24, min_periods=24).std().shift(1)      # vol known BEFORE bar t
    f["sig72"] = lr.rolling(72, min_periods=72).std().shift(1)
    f["sig168"] = lr.rolling(168, min_periods=168).std().shift(1)
    f["z1"] = lr / f["sig168"]
    f["atr24"] = ta.atr(df, 24)
    f["atr24_prev"] = f["atr24"].shift(1)
    f["atrp"] = f["atr24"] / c
    usd = v * c
    f["usd"] = usd
    f["vmed168"] = usd.rolling(168, min_periods=100).median().shift(1)
    f["vrel"] = usd / f["vmed168"]
    f["er24"] = ta.efficiency_ratio(c, 24)
    f["er48"] = ta.efficiency_ratio(c, 48)
    f["rsi14"] = ta.rsi(c, 14)
    f["z24"] = ta.zscore(c, 24)
    f["z48"] = ta.zscore(c, 48)
    f["ret4"] = c / c.shift(4) - 1.0
    f["ret12"] = c / c.shift(12) - 1.0
    f["ret24"] = c / c.shift(24) - 1.0
    f["ret72"] = c / c.shift(72) - 1.0
    f["ret168"] = c / c.shift(168) - 1.0
    rng = (h - l).replace(0, np.nan)
    f["lwick"] = (np.minimum(o, c) - l)
    f["uwick"] = (h - np.maximum(o, c))
    f["clv"] = (c - l) / rng                      # close location in the bar 0..1
    f["rng"] = (h - l)
    return f


def panel(data=None, extra=None) -> pd.DataFrame:
    """Long panel: one row per (symbol, bar) with features, labels, tradable flag."""
    data = data or load()
    parts = []
    for s, df in data.items():
        f = base_features(df)
        if extra is not None:
            e = extra(s, df, data)
            if e is not None:
                f = f.join(e)
        lab = add_labels(df)
        x = pd.concat([df, f, lab], axis=1)
        x["tradable"] = store.tradable_mask(s, df.index).to_numpy()
        x["sym"] = s
        x["year"] = df.index.year
        x["major"] = s in MAJORS
        parts.append(x)
    p = pd.concat(parts).reset_index().rename(columns={"index": "time"})
    return p


def cluster_t(x: pd.Series, cl: pd.Series) -> float:
    """t-stat of the mean with errors clustered on `cl` (events on the same day are not independent)."""
    x = x.astype(float)
    ok = x.notna()
    x, cl = x[ok], cl[ok]
    n = len(x)
    if n < 5:
        return np.nan
    m = x.mean()
    g = (x - m).groupby(cl.to_numpy()).sum()
    G = len(g)
    if G < 3:
        return np.nan
    se = np.sqrt((g ** 2).sum()) / n * np.sqrt(G / (G - 1))
    return float(m / se) if se > 0 else np.nan


def stats(ev: pd.DataFrame, col: str, sign: float | pd.Series = 1.0) -> dict:
    """Mean / median / hit / t of signed forward return `col` in bps."""
    r = (ev[col] * sign).dropna()
    if len(r) == 0:
        return dict(n=0)
    day = ev.loc[r.index, "time"].dt.floor("D")
    return dict(
        n=len(r), days=day.nunique(),
        mean=r.mean() * 1e4, med=r.median() * 1e4, hit=(r > 0).mean(),
        t=r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if len(r) > 2 and r.std() > 0 else np.nan,
        t_cl=cluster_t(r, day),
        p05=r.quantile(0.05) * 1e4, p01=r.quantile(0.01) * 1e4, worst=r.min() * 1e4,
    )


def dedupe(ev: pd.DataFrame, gap: int) -> pd.DataFrame:
    """Keep an event only if the same symbol had no kept event in the previous `gap` bars
    (one position per symbol: an overlapping signal would be ignored by the engine)."""
    keep = []
    for s, g in ev.groupby("sym", sort=False):
        last = None
        for idx, t in zip(g.index, g["time"]):
            if last is None or (t - last) >= pd.Timedelta(hours=gap):
                keep.append(idx)
                last = t
    return ev.loc[keep]


def report(ev: pd.DataFrame, hs=(1, 4, 12, 24), sign=1.0, title="", by_year=True, hold=None) -> pd.DataFrame:
    rows = []
    for h in hs:
        for suf, lab in (("", "next-open"), ("_d", "delayed+1")):
            d = stats(ev, f"fwd_{h}{suf}", sign)
            d.update(h=h, entry=lab, split="all")
            rows.append(d)
    hh = hold or hs[-1]
    if by_year:
        for y, g in ev.groupby("year"):
            d = stats(g, f"fwd_{hh}", sign if np.isscalar(sign) else sign.loc[g.index])
            d.update(h=hh, entry="next-open", split=str(y))
            rows.append(d)
        for nm, g in (("majors", ev[ev["major"]]), ("alts", ev[~ev["major"]])):
            if len(g):
                d = stats(g, f"fwd_{hh}", sign if np.isscalar(sign) else sign.loc[g.index])
                d.update(h=hh, entry="next-open", split=nm)
                rows.append(d)
    out = pd.DataFrame(rows)
    cols = ["split", "h", "entry", "n", "days", "mean", "med", "hit", "t", "t_cl", "p05", "p01", "worst"]
    out = out[[c for c in cols if c in out.columns]]
    if title:
        print(f"\n=== {title} ===")
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:,.2f}"):
        print(out.to_string(index=False))
    return out
