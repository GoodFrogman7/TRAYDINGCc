"""H6 air-pocket drops (big bar, ordinary volume), idiosyncratic high-volume dumps/pumps, spread stress."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
btc = P["PF_XBTUSD"]
for s, f in P.items():
    f["btc_rz"] = btc.rz.reindex(f.index)
    f["btc_volrel"] = btc.vol_rel.reindex(f.index)
    f["btc_ret4"] = btc.ret4.reindex(f.index)
    if "half_spread_bps" in f:
        f["sp_rel"] = f["half_spread_bps"] / f["half_spread_bps"].rolling(168, min_periods=48).median().shift(1)
        f["sp100_rel"] = f["half_spread100_bps"] / f["half_spread100_bps"].rolling(168, min_periods=48).median().shift(1)
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()

def rep(E, name, d=1, hs=(1, 4, 12, 24)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        out.append(s)
    return out

print("=== big down bar rz<=-3 by relative volume (LONG fade) ===")
out = []
for lo, hi in ((0, 1.5), (1.5, 2.5), (2.5, 4), (4, 8), (8, 16), (16, 9999)):
    out += rep(X[(X.rz <= -3) & (X.vol_rel > lo) & (X.vol_rel <= hi)], f"dn vol_rel ({lo},{hi}]", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))
print("\n=== big up bar rz>=3 by relative volume (SHORT fade) ===")
out = []
for lo, hi in ((0, 1.5), (1.5, 2.5), (2.5, 4), (4, 8), (8, 16), (16, 9999)):
    out += rep(X[(X.rz >= 3) & (X.vol_rel > lo) & (X.vol_rel <= hi)], f"up vol_rel ({lo},{hi}]", d=-1, hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== idiosyncratic alt moves: |rz|>=3, vol_rel>=8, BTC quiet (|btc_rz|<1) ===")
out = []
A = X[~X.maj]
out += rep(A[(A.rz <= -3) & (A.vol_rel >= 8) & (A.btc_rz.abs() < 1)], "idio dump -> SHORT (continuation)", d=-1, hs=(4, 12, 24, 48))
out += rep(A[(A.rz >= 3) & (A.vol_rel >= 8) & (A.btc_rz.abs() < 1)], "idio pump -> LONG (continuation)", d=1, hs=(4, 12, 24, 48))
out += rep(A[(A.rz >= 4) & (A.vol_rel >= 8) & (A.btc_rz.abs() < 1)], "idio pump rz>=4 -> LONG (continuation)", d=1, hs=(4, 12, 24, 48))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== spread stress (from 2023-06): $10k half-spread >= k x trailing 7d median ===")
S = X[X.sp_rel.notna()]
print("n with spread", len(S), S.sp_rel.describe().round(2).to_dict())
out = []
for k in (2, 3):
    out += rep(S[(S.sp_rel >= k) & (S.ret4 < -2 * S.atrp)], f"spread>={k}x & 4h drop>2ATR -> LONG", hs=(4, 12, 24))
    out += rep(S[(S.sp_rel >= k) & (S.ret4 > 2 * S.atrp)], f"spread>={k}x & 4h rise>2ATR -> SHORT", d=-1, hs=(4, 12, 24))
    out += rep(S[(S.sp_rel < 1.5) & (S.ret4 < -2 * S.atrp)], f"spread normal & 4h drop>2ATR -> LONG", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))
