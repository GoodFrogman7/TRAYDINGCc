"""H1: liquidation spikes -> snapback or continuation? And is it just a big-bar proxy?"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()
print("tradable bars", len(X))
HS = (1, 4, 12, 24, 48)

def tab(E, name, hs=HS, signed=True):
    rows = []
    for h in hs:
        r = E[f"f{h}"] * (E["dir"] if signed else 1)
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); rows.append(s)
    return pd.DataFrame(rows)

# --- definition: liq spike = liq_vol > trailing 720h 99th pct AND liq_rel (liq / mean hourly vol) >= x
X["spike"] = (X.liq > X.liq_q99) & (X.liq > 0)
print("spike bars", X.spike.sum(), "share", X.spike.mean().round(4))
print(X[X.spike][["liq_rel", "liq_share", "rz", "vol_rel", "body"]].describe().round(3))

# Fade direction: liquidations in a DOWN bar = longs liquidated -> fade = long (dir=+1)
for thr in (0.0, 0.1, 0.3):
    for rzmin in (0, 2, 3):
        E = X[X.spike & (X.liq_rel >= thr) & (X.rz.abs() >= rzmin)].copy()
        E["dir"] = -np.sign(E.body)
        E = E[E.dir != 0]
        t = tab(E, f"FADE liq_rel>={thr} |rz|>={rzmin}")
        print(t.to_string(index=False))
    print()
