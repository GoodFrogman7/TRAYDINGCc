"""H1b: liq spike split by direction, year, breadth; control = equally big bars WITHOUT liq spike."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()
X["spike"] = (X.liq > X.liq_q99) & (X.liq > 0)
X["down"] = X.body < 0
# breadth: number of tradable symbols with a liq spike in the same hour
X["breadth"] = X.groupby("time")["spike"].transform("sum")
X["nbig"] = X.assign(b=(X.rz.abs() >= 3)).groupby("time")["b"].transform("sum")

def rows(E, name, hs=(1, 4, 12, 24, 48)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * E["dir"]
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); out.append(s)
    return out

print("=== big DOWN bars (rz<=-3): liq spike vs no spike (fade = long) ===")
out = []
for nm, m in (("down rz<=-3 SPIKE", X.spike & (X.rz <= -3)), ("down rz<=-3 NO spike", ~X.spike & (X.rz <= -3)),
              ("down rz<=-3 NO liq at all", (X.liq == 0) & (X.rz <= -3)),
              ("up rz>=3 SPIKE (fade=short)", X.spike & (X.rz >= 3)), ("up rz>=3 NO spike (fade=short)", ~X.spike & (X.rz >= 3))):
    E = X[m].copy(); E["dir"] = -np.sign(E.rz)
    out += rows(E, nm)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== match on bar size: rz buckets, spike vs no spike, long fade of down bars, h=12/24 ===")
out = []
for lo, hi in ((-2.5, -1.5), (-4, -2.5), (-6, -4), (-99, -6)):
    for nm, m in (("spike", X.spike), ("nospike", ~X.spike)):
        E = X[m & (X.rz > lo) & (X.rz <= hi)].copy(); E["dir"] = 1
        for h in (4, 12, 24):
            s = lib.stats(E[f"f{h}"], f"rz({lo},{hi}] {nm} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=E[f"f{h}"])); s["med_rz"] = round(E.rz.median(), 2); out.append(s)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== spike & rz<=-3 by year / maj / breadth (long), h=12 & 24 ===")
E = X[X.spike & (X.rz <= -3)].copy(); E["dir"] = 1
out = []
for h in (12, 24):
    for k, g in E.groupby("year"): out.append(lib.stats(g[f"f{h}"], f"h={h} year={k}"))
    for k, g in E.groupby("maj"): out.append(lib.stats(g[f"f{h}"], f"h={h} maj={k}"))
    for nm, m in (("breadth=1", E.breadth == 1), ("breadth 2-3", E.breadth.between(2, 3)), ("breadth>=4", E.breadth >= 4)):
        out.append(lib.stats(E[m][f"f{h}"], f"h={h} {nm}"))
    out.append(lib.stats(E[f"f{h}d"], f"h={h} delayed+1"))
print(pd.DataFrame(out).to_string(index=False))
print("days with events:", E.time.dt.floor("D").nunique(), "top days:")
print(E.groupby(E.time.dt.floor("D")).agg(n=("f24", "size"), f24=("f24", "mean")).sort_values("n", ascending=False).head(15).round(4))

print("\n=== spike & rz>=3 (short squeeze): continuation (long) by year, h=12 & 24 ===")
E = X[X.spike & (X.rz >= 3)].copy()
out = []
for h in (4, 12, 24, 48):
    out.append(lib.stats(E[f"f{h}"], f"h={h} all LONG-continuation"))
    for k, g in E.groupby("year"): out.append(lib.stats(g[f"f{h}"], f"h={h} year={k}"))
print(pd.DataFrame(out).to_string(index=False))
