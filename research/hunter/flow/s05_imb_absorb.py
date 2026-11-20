"""H2 absorption (volume surge, no price progress, one-sided aggressor flow) and H3 aggressor-imbalance persistence/exhaustion."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
for s, f in P.items():
    # trailing ranks (causal)
    f["imb_q"] = f["imb"].rolling(720, min_periods=360).rank(pct=True)
    f["imb24_q"] = f["imb24"].rolling(720, min_periods=360).rank(pct=True)
    f["imb72_q"] = f["imb72"].rolling(720, min_periods=360).rank(pct=True)
    f["imb24_z"] = (f["imb24"] - f["imb24"].rolling(720, min_periods=360).mean()) / f["imb24"].rolling(720, min_periods=360).std()
    f["absr"] = f["body"].abs() / f["atrp"]
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()

def rep(E, name, d, hs=(4, 12, 24, 48)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r))
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        out.append(s)
    return out

print("imb distribution:", X.imb.describe().round(3).to_dict())
print("corr(imb, body)", round(X.imb.corr(X.body), 3), " corr(imb24, ret24)", round(X.imb24.corr(X.ret24), 3))

print("\n=== H3a: single-bar imbalance deciles -> fwd (raw long returns, bps) ===")
X["imb_dec"] = pd.cut(X.imb_q, [0, .02, .1, .3, .7, .9, .98, 1.0])
print((X.groupby("imb_dec", observed=True)[["f1", "f4", "f12", "f24"]].mean() * 1e4).round(1).assign(n=X.groupby("imb_dec", observed=True).size()))
print("\n=== H3b: 24h imbalance rank buckets -> fwd (raw) ===")
X["i24"] = pd.cut(X.imb24_q, [0, .02, .1, .3, .7, .9, .98, 1.0])
print((X.groupby("i24", observed=True)[["f4", "f12", "f24", "f48"]].mean() * 1e4).round(1).assign(n=X.groupby("i24", observed=True).size()))
print("by year, f24:")
print((X.groupby(["year", "i24"], observed=True)["f24"].mean().unstack(0) * 1e4).round(1))
print("\n=== H3c: 72h imbalance rank buckets -> fwd (raw) by year, f48 ===")
X["i72"] = pd.cut(X.imb72_q, [0, .02, .1, .3, .7, .9, .98, 1.0])
print((X.groupby(["year", "i72"], observed=True)["f48"].mean().unstack(0) * 1e4).round(1))

print("\n=== H3d: divergence: 24h aggressor flow strongly one-sided but price went the other way ===")
out = []
for q in (0.1, 0.05):
    E = X[(X.imb24_q <= q) & (X.ret24 > 0)]; out += rep(E, f"sellers aggress (imb24_q<={q}) but ret24>0 -> LONG", 1)
    E = X[(X.imb24_q >= 1 - q) & (X.ret24 < 0)]; out += rep(E, f"buyers aggress (imb24_q>={1-q}) but ret24<0 -> SHORT", -1)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== H2: absorption bar: volume surge (vol_rel>=k), tiny body (|body|<0.25 ATR), one-sided aggressor ===")
out = []
for k in (3, 5):
    base = (X.vol_rel >= k) & (X.absr < 0.25)
    out += rep(X[base & (X.imb <= -0.2)], f"vol_rel>={k} tiny body, sell-aggr (imb<=-0.2) -> LONG", 1)
    out += rep(X[base & (X.imb >= 0.2)], f"vol_rel>={k} tiny body, buy-aggr (imb>=0.2) -> SHORT", -1)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== H2b: volume surge WITH progress (vol_rel>=5, |rz|>=3): continuation by direction ===")
out = []
out += rep(X[(X.vol_rel >= 5) & (X.rz >= 3)], "surge up -> LONG", 1)
out += rep(X[(X.vol_rel >= 5) & (X.rz <= -3)], "surge down -> SHORT", -1)
out += rep(X[(X.vol_rel < 2) & (X.rz >= 3)], "big up on LOW volume -> SHORT(fade)", -1)
out += rep(X[(X.vol_rel < 2) & (X.rz <= -3)], "big down on LOW volume -> LONG(fade)", 1)
print(pd.DataFrame(out).to_string(index=False))
