"""Shared helpers for the carry lens (funding / basis / positioning). DESIGN WINDOW ONLY."""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import numpy as np
import pandas as pd
from desk.data import store

MAJORS = {"PF_XBTUSD", "PF_ETHUSD"}


def load():
    data = store.load_design()
    out = {}
    for s, df in data.items():
        df = df.copy()
        df["tradable"] = store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool)
        out[s] = df
    return out


def fwd_ret(df: pd.DataFrame, h: int, delay: int = 0) -> pd.Series:
    """Return from open of bar t+1+delay to open of bar t+1+delay+h (signal at close of t)."""
    o = df["open"]
    return o.shift(-(1 + delay + h)) / o.shift(-(1 + delay)) - 1.0


def fwd_funding(df: pd.DataFrame, h: int, delay: int = 0) -> pd.Series:
    """Sum of funding over bars t+1+delay .. t+delay+h (what a long pays)."""
    f = df["funding"].fillna(0.0)
    cs = f.cumsum()
    return cs.shift(-(delay + h)) - cs.shift(-delay)


def decluster(mask: pd.Series, gap: int) -> pd.Series:
    """Keep an event only if no kept event in the previous `gap` bars (causal)."""
    m = mask.to_numpy(dtype=bool)
    out = np.zeros(len(m), dtype=bool)
    last = -10**9
    for i in np.nonzero(m)[0]:
        if i - last >= gap:
            out[i] = True
            last = i
    return pd.Series(out, index=mask.index)


def stats(r: pd.Series | np.ndarray) -> dict:
    r = pd.Series(r).dropna()
    n = len(r)
    if n < 2:
        return dict(n=n, mean=np.nan, med=np.nan, hit=np.nan, t=np.nan)
    return dict(n=n, mean=r.mean() * 1e4, med=r.median() * 1e4, hit=(r > 0).mean(), t=r.mean() / r.std(ddof=1) * np.sqrt(n))


def fmt(d: dict) -> str:
    return f"n={d['n']:5d} mean={d['mean']:8.1f}bp med={d['med']:8.1f}bp hit={d['hit']:.2f} t={d['t']:5.2f}"


def study(events: pd.DataFrame, col: str = "r", label: str = "") -> None:
    """events: rows with columns time, sym, side, r (signed fwd return), optionally r_d1 (delayed)."""
    if len(events) == 0:
        print(label, "NO EVENTS"); return
    print(f"== {label}")
    print("  all   ", fmt(stats(events[col])))
    for y in sorted(events["time"].dt.year.unique()):
        print(f"  {y}  ", fmt(stats(events.loc[events['time'].dt.year == y, col])))
    for sd, nm in ((1, "long "), (-1, "short")):
        e = events[events["side"] == sd]
        if len(e):
            print(f"  {nm} ", fmt(stats(e[col])))
    maj = events["sym"].isin(MAJORS)
    if maj.any():
        print("  BTCETH", fmt(stats(events.loc[maj, col])))
    if (~maj).any():
        print("  alts  ", fmt(stats(events.loc[~maj, col])))
    if "r_d1" in events:
        print("  delay1", fmt(stats(events["r_d1"])))
    if "fund" in events:
        print(f"  funding paid over hold (signed, bps): mean={events['fund'].mean()*1e4:.2f}")
    # cluster-robust: daily mean
    dm = events.groupby(events["time"].dt.floor("D"))[col].mean()
    print("  by-day", fmt(stats(dm)), f"(distinct days={len(dm)})")


def collect(data: dict, sig_fn, h: int, gap: int | None = None) -> pd.DataFrame:
    """sig_fn(df, sym) -> Series of side in {-1,0,1} decided at close of t. Returns event table."""
    rows = []
    for s, df in data.items():
        sg = sig_fn(df, s)
        if sg is None:
            continue
        sg = sg.fillna(0).astype(int)
        sg = sg.where(df["tradable"], 0)
        for sd in (1, -1):
            m = sg == sd
            if not m.any():
                continue
            if gap:
                m = decluster(m, gap)
            idx = df.index[m.to_numpy()]
            r = fwd_ret(df, h)[m.to_numpy()] * sd
            r1 = fwd_ret(df, h, 1)[m.to_numpy()] * sd
            fu = fwd_funding(df, h)[m.to_numpy()] * sd
            rows.append(pd.DataFrame({"time": idx, "sym": s, "side": sd, "r": r.to_numpy(), "r_d1": r1.to_numpy(), "fund": fu.to_numpy()}))
    if not rows:
        return pd.DataFrame(columns=["time", "sym", "side", "r", "r_d1", "fund"])
    return pd.concat(rows, ignore_index=True)


def line(events: pd.DataFrame, label: str, col: str = "r") -> None:
    """Compact one-block summary."""
    if len(events) == 0:
        print(f"{label}: NO EVENTS"); return
    s = stats(events[col])
    yrs = " ".join(f"{y}:{stats(events.loc[events['time'].dt.year == y, col])['mean']:.0f}({(events['time'].dt.year == y).sum()})" for y in sorted(events["time"].dt.year.unique()))
    dm = events.groupby(events["time"].dt.floor("D"))[col].mean()
    sd = stats(dm)
    maj = events["sym"].isin(MAJORS)
    mj = stats(events.loc[maj, col]) if maj.sum() > 1 else dict(mean=np.nan, n=0)
    al = stats(events.loc[~maj, col]) if (~maj).sum() > 1 else dict(mean=np.nan, n=0)
    d1 = stats(events["r_d1"])["mean"] if "r_d1" in events else np.nan
    sides = " ".join(f"{nm}:{stats(events.loc[events['side'] == sd_, col])['mean']:.0f}({(events['side'] == sd_).sum()})" for sd_, nm in ((1, "L"), (-1, "S")) if (events["side"] == sd_).sum() > 1)
    print(f"{label}\n    n={s['n']} mean={s['mean']:.1f} med={s['med']:.1f} hit={s['hit']:.2f} t={s['t']:.2f} | byday t={sd['t']:.2f} days={sd['n']} | {yrs} | {sides} | maj={mj['mean']:.0f}({mj['n']}) alts={al['mean']:.0f}({al['n']}) | delay1={d1:.1f} | fund={events['fund'].mean()*1e4:.1f}")
