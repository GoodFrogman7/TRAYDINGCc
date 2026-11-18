"""Build the causal feature panel for the flow lens (design window only)."""
from __future__ import annotations
import sys, pickle, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import lib
from desk.strategies import ta

HS = (1, 2, 4, 8, 12, 24, 48, 72)
CACHE = os.environ.get("FLOW_CACHE", "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/flow_panel.pkl")


def feats(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    f["close"], f["open"], f["high"], f["low"] = c, o, h, l
    f["tradable"] = df["tradable"]
    f["miss"] = df["bar_missing"]
    f["atr"] = ta.atr(df, 24)
    f["atrp"] = f["atr"] / c
    f["r1"] = c / c.shift(1) - 1
    f["body"] = c / o - 1
    sd = f["r1"].rolling(168, min_periods=100).std().shift(1)
    f["rz"] = f["r1"] / sd
    f["sd168"] = sd
    for k in (2, 4, 8, 12, 24, 48, 72, 168):
        f[f"ret{k}"] = c / c.shift(k) - 1
    vmed = v.rolling(168, min_periods=100).median().shift(1)
    vmean = v.rolling(168, min_periods=100).mean().shift(1)
    f["vol_rel"] = v / vmed.replace(0, np.nan)
    f["vol_relm"] = v / vmean.replace(0, np.nan)
    f["usd_vol"] = v * c
    liq = df["liq_vol"].fillna(0.0)
    f["liq"] = liq
    f["liq_usd"] = liq * c
    f["liq_share"] = liq / v.replace(0, np.nan)
    f["liq_rel"] = liq / vmean.replace(0, np.nan)          # liq vs normal hourly volume
    f["liq_q99"] = liq.rolling(720, min_periods=360).quantile(0.99).shift(1)
    f["liq_q995"] = liq.rolling(720, min_periods=360).quantile(0.995).shift(1)
    f["liq_max720"] = liq.rolling(720, min_periods=360).max().shift(1)
    f["liq4"] = liq.rolling(4).sum()
    f["liq4_rel"] = f["liq4"] / (4 * vmean.replace(0, np.nan))
    bv, sv = df["buy_vol"], df["sell_vol"]
    tot = (bv + sv).replace(0, np.nan)
    f["imb"] = (bv - sv) / tot
    for k in (4, 12, 24, 72):
        f[f"imb{k}"] = (bv - sv).rolling(k, min_periods=k).sum() / (bv + sv).rolling(k, min_periods=k).sum().replace(0, np.nan)
    f["bs_cov"] = (bv + sv) / v.replace(0, np.nan)
    f["rv24"] = ta.realized_vol(c, 24)
    f["rv72"] = ta.realized_vol(c, 72)
    f["rv168"] = ta.realized_vol(c, 168)
    f["rv720"] = ta.realized_vol(c, 720)
    f["bbw"] = ta.bb_width(c, 48, 2.0)
    f["bbw_rank"] = ta.rolling_rank(f["bbw"], 720)
    f["rng"] = (h - l) / c
    f["clpos"] = (c - l) / (h - l).replace(0, np.nan)
    f["hh24"] = h.shift(1).rolling(24).max(); f["ll24"] = l.shift(1).rolling(24).min()
    f["hh72"] = h.shift(1).rolling(72).max(); f["ll72"] = l.shift(1).rolling(72).min()
    f["hh168"] = h.shift(1).rolling(168).max(); f["ll168"] = l.shift(1).rolling(168).min()
    f["sma168"] = ta.sma(c, 168)
    f["funding"] = df["funding"]
    if "bid_10k" in df:
        mid = (df["ask_10k"] + df["bid_10k"]) / 2
        f["half_spread_bps"] = (df["ask_10k"] - df["bid_10k"]) / mid / 2 * 1e4
        f["half_spread100_bps"] = (df["ask_100k"] - df["bid_100k"]) / ((df["ask_100k"] + df["bid_100k"]) / 2) / 2 * 1e4
    f["oi"] = df.get("oi")
    # forward returns from next open (signal at close t, entry open t+1)
    for hh in HS:
        f[f"f{hh}"] = lib.fwd(df, hh, 0)
        f[f"f{hh}d"] = lib.fwd(df, hh, 1)
    # forward path extremes over next N bars relative to entry open (for stop sanity)
    ent = o.shift(-1)
    for hh in (12, 24, 48):
        f[f"mae{hh}_lo"] = l.shift(-1)[::-1].rolling(hh, min_periods=hh).min()[::-1] / ent - 1  # study only (forward-looking label)
        f[f"mfe{hh}_hi"] = h.shift(-1)[::-1].rolling(hh, min_periods=hh).max()[::-1] / ent - 1
    return f


def panel(rebuild=False):
    if os.path.exists(CACHE) and not rebuild:
        return pickle.load(open(CACHE, "rb"))
    d = lib.load()
    assert all(df.index.max() < pd.Timestamp("2025-01-01", tz="UTC") for df in d.values())
    P = {s: feats(df) for s, df in d.items()}
    pickle.dump(P, open(CACHE, "wb"))
    return P


def stack(P, cols=None):
    out = []
    for s, f in P.items():
        g = f if cols is None else f[cols]
        g = g.copy(); g["sym"] = s; g["time"] = g.index
        out.append(g)
    X = pd.concat(out, ignore_index=True)
    X["year"] = X["time"].dt.year
    X["maj"] = X["sym"].isin(lib.MAJ)
    return X


if __name__ == "__main__":
    P = panel(rebuild=True)
    X = stack(P)
    print(X.shape, X["tradable"].sum())
    print(X.loc[X.tradable, ["bs_cov", "liq_share", "liq_rel", "vol_rel", "atrp", "imb"]].describe().round(4))
    if "half_spread_bps" in X:
        print(X[X.tradable].groupby("sym")["half_spread_bps"].median().round(2))
