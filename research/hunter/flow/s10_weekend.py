"""H7b: is 'thin-weekend move continues when weekday liquidity returns' real? Day-of-week control, entry hour, thresholds."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
for s, f in P.items():
    f["dow"] = f.index.dayofweek; f["hr"] = f.index.hour
    f["wk_ret"] = f["close"] / f["close"].shift(48) - 1
    f["wk_z"] = f["wk_ret"] / (f["sd168"] * np.sqrt(48))
    f["wk_atr"] = (f["close"] - f["close"].shift(48)) / f["atr"]
    f["v48"] = f["usd_vol"].rolling(48).sum()
    f["v48_rel"] = f["v48"] / (f["usd_vol"].rolling(720).sum().shift(1) / 15)      # 48h volume vs avg 48h volume of last 30d
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()

def rep(E, name, d=1, hs=(12, 24, 48)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        out.append(s)
    return out

print("distribution of wk_z at Sunday 21:00:", X[(X.dow == 6) & (X.hr == 21)].wk_z.describe().round(2).to_dict())
print("\n=== 48h move z<=-1 / >=+1 measured at 21:00 UTC, by day of week (continuation: d = sign of move), h=24 ===")
out = []
for dow in range(7):
    D = X[(X.dow == dow) & (X.hr == 21)]
    for nm, m, d in (("down", D.wk_z <= -1, -1), ("up", D.wk_z >= 1, 1)):
        E = D[m]; r = E["f24"] * d
        s = lib.stats(r, f"dow={dow} {nm} continuation h=24"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        out.append(s)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== per-weekend detail, Sunday 21:00, wk_z<=-1 (short continuation) ===")
E = X[(X.dow == 6) & (X.hr == 21) & (X.wk_z <= -1)]
print(E.groupby(E.time.dt.date).agg(n=("f24", "size"), wk_ret=("wk_ret", "mean"), f12=("f12", "mean"), f24=("f24", "mean"), f48=("f48", "mean")).round(4).to_string())
print("\n=== per-weekend detail, Sunday 21:00, wk_z>=1 (long continuation) ===")
E = X[(X.dow == 6) & (X.hr == 21) & (X.wk_z >= 1)]
g = E.groupby(E.time.dt.date).agg(n=("f24", "size"), wk_ret=("wk_ret", "mean"), f12=("f12", "mean"), f24=("f24", "mean"), f48=("f48", "mean")).round(4)
print(g.to_string())
print("day-level: mean f24", g.f24.mean().round(4), "hit", (g.f24 > 0).mean().round(2), "n days", len(g))

print("\n=== threshold / entry-hour robustness (Sunday), continuation, h=24 ===")
out = []
for hr in (17, 21, 23):
    for z in (0.75, 1.0, 1.25):
        D = X[(X.dow == 6) & (X.hr == hr)]
        out += rep(D[D.wk_z <= -z], f"Sun {hr}h z<=-{z} SHORT", -1, hs=(24,))
        out += rep(D[D.wk_z >= z], f"Sun {hr}h z>={z} LONG", 1, hs=(24,))
print(pd.DataFrame(out).to_string(index=False))
