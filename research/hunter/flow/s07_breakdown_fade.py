"""H4b: breakdowns to a new 48h closing low: reversal depends on the volatility state they occur in."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
btc = P["PF_XBTUSD"]
for s, f in P.items():
    f["bbw_rank_prev"] = f["bbw_rank"].shift(1)
    f["rvr"] = (f["rv24"] / f["rv720"])
    f["rvr_prev"] = f["rvr"].shift(1)
    f["dn48"] = f["close"] < f["low"].shift(1).rolling(48).min()
    f["up48"] = f["close"] > f["high"].shift(1).rolling(48).max()
    f["dn48_first"] = lib.dedupe(f["dn48"], 12)
    f["btc_rz"] = btc.rz.reindex(f.index)
    f["drop48"] = f["close"] / f["high"].rolling(48).max() - 1       # drawdown from 48h high
    f["drop_atr"] = (f["high"].rolling(48).max() - f["close"]) / f["atr"]
X = F.stack(P)
X = X[X.tradable & ~X.miss].copy()

def rep(E, name, d=1, hs=(4, 12, 24, 48)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        out.append(s)
    return out

print("=== breakdown (close < prior 48h low) LONG fade, by prior BB-width rank bucket ===")
out = []
for lo, hi in ((0, .15), (.15, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)):
    out += rep(X[X.dn48 & (X.bbw_rank_prev > lo) & (X.bbw_rank_prev <= hi)], f"bbw_rank ({lo},{hi}]", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== same, by rv24/rv720 ratio (prev bar) ===")
out = []
for lo, hi in ((0, .7), (.7, 1.0), (1.0, 1.4), (1.4, 2.0), (2.0, 99)):
    out += rep(X[X.dn48 & (X.rvr_prev > lo) & (X.rvr_prev <= hi)], f"rvr ({lo},{hi}]", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== by size of the breakdown bar (rz) given bbw_rank_prev>0.5 ===")
out = []
B = X[X.dn48 & (X.bbw_rank_prev > 0.5)]
for lo, hi in ((-99, -4), (-4, -2.5), (-2.5, -1.5), (-1.5, 0)):
    out += rep(B[(B.rz > lo) & (B.rz <= hi)], f"rz ({lo},{hi}]", hs=(4, 12, 24))
print("--- by vol_rel"); 
for lo, hi in ((0, 2), (2, 4), (4, 8), (8, 999)):
    out += rep(B[(B.vol_rel > lo) & (B.vol_rel <= hi)], f"vol_rel ({lo},{hi}]", hs=(4, 12, 24))
out += rep(B[B.maj], "majors", hs=(4, 12, 24)); out += rep(B[~B.maj], "alts", hs=(4, 12, 24))
out += rep(B[B.dn48_first], "first breakdown in 12 bars", hs=(4, 12, 24))
out += rep(B[~B.dn48_first], "repeat breakdown", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== mirror: breakout UP (close > prior 48h high) SHORT fade given bbw_rank_prev>0.5, by rz ===")
out = []
U = X[X.up48 & (X.bbw_rank_prev > 0.5)]
for lo, hi in ((4, 99), (2.5, 4), (1.5, 2.5), (0, 1.5)):
    out += rep(U[(U.rz >= lo) & (U.rz < hi)], f"up rz [{lo},{hi})", d=-1, hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))
