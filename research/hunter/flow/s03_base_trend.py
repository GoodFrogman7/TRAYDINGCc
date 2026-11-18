"""Baseline drift per year, and H1c: liquidation flush conditioned on higher-timeframe trend + breadth."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
# BTC regime features (causal): BTC close vs its 720h SMA, BTC 720h return
btc = P["PF_XBTUSD"]
breg = pd.DataFrame({"btc_ret720": btc.close / btc.close.shift(720) - 1,
                     "btc_above": btc.close > btc.close.rolling(720).mean(),
                     "btc_rz": btc.rz, "btc_ret4": btc.ret4})
for s in P:
    for c in breg: P[s][c] = breg[c].reindex(P[s].index)
    P[s]["above720"] = P[s].close > P[s].close.rolling(720).mean()
    P[s]["ret720"] = P[s].close / P[s].close.shift(720) - 1
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()
print("=== unconditional drift (bps) per year, tradable bars ===")
print((X.groupby("year")[["f4", "f12", "f24", "f48"]].mean() * 1e4).round(1))
print((X.groupby(["year", "maj"])[["f24"]].mean() * 1e4).round(1).T)

X["spike"] = (X.liq > X.liq_q99) & (X.liq > 0)
X["breadth"] = X.groupby("time")["spike"].transform("sum")

def rep(E, name, d, hs=(4, 12, 24, 48)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r))
        for y in (2022, 2023, 2024):
            g = r[E.year == y]; s[f"y{y}"] = f"{g.mean()*1e4:.0f}/{len(g)}"
        rd = E[f"f{h}d"] * d; s["delay"] = round(rd.mean() * 1e4, 1)
        out.append(s)
    return out

out = []
dn = X.spike & (X.rz <= -3)
up = X.spike & (X.rz >= 3)
out += rep(X[dn & X.above720], "LONG flush, sym above SMA720", 1)
out += rep(X[dn & ~X.above720], "LONG flush, sym below SMA720", 1)
out += rep(X[dn & X.btc_above], "LONG flush, BTC above SMA720", 1)
out += rep(X[dn & ~X.btc_above], "LONG flush, BTC below SMA720", 1)
out += rep(X[up & X.above720], "SHORT squeeze, sym above SMA720", -1)
out += rep(X[up & ~X.above720], "SHORT squeeze, sym below SMA720", -1)
out += rep(X[up & X.btc_above], "SHORT squeeze, BTC above", -1)
out += rep(X[up & ~X.btc_above], "SHORT squeeze, BTC below", -1)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== breadth >= 4 flush (long) by year; and rz<=-5 ===")
out = []
out += rep(X[dn & (X.breadth >= 4)], "LONG flush breadth>=4", 1)
out += rep(X[dn & (X.breadth >= 3)], "LONG flush breadth>=3", 1)
out += rep(X[dn & (X.breadth <= 2)], "LONG flush breadth<=2", 1)
out += rep(X[X.spike & (X.rz <= -5)], "LONG flush rz<=-5", 1)
out += rep(X[X.spike & (X.rz <= -5) & (X.breadth >= 3)], "LONG flush rz<=-5 breadth>=3", 1)
print(pd.DataFrame(out).to_string(index=False))
print("\n2022 liq coverage: share of tradable bars with liq>0 by year")
print(X.groupby("year").agg(liqpos=("liq", lambda s: (s > 0).mean()), spikes=("spike", "sum"), n=("liq", "size")))
