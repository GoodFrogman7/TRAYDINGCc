"""H1d: is the market-wide flush edge about LIQUIDATIONS or just about a market-wide big down bar?"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
A = F.stack(P)                       # ALL symbols in the data set (breadth can use non-tradable ones too)
A = A[~A.miss].copy()
A["spike"] = (A.liq > A.liq_q99) & (A.liq > 0)
A["dspike"] = A.spike & (A.body < 0)
A["bigdn"] = A.rz <= -3
g = A.groupby("time")
A["b_spk_all"] = g["dspike"].transform("sum")          # liq-spike-down breadth over all listed symbols
A["b_big_all"] = g["bigdn"].transform("sum")
A["n_all"] = g["rz"].transform("count")
A["b_spk_trd"] = A.assign(x=A.dspike & A.tradable).groupby("time")["x"].transform("sum")
A["b_big_trd"] = A.assign(x=A.bigdn & A.tradable).groupby("time")["x"].transform("sum")
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz, "btc_liq_rel": btc.liq_rel})
A = A.join(bs, on="time")
X = A[A.tradable].copy()

def rep(E, name, d=1, hs=(4, 12, 24)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        out.append(s)
    return out

out = []
big = X.rz <= -3
out += rep(X[big & (X.b_big_trd >= 4) & (X.b_spk_trd >= 3)], "bigdn: bigbreadth>=4 & liqbreadth>=3")
out += rep(X[big & (X.b_big_trd >= 4) & (X.b_spk_trd <= 1)], "bigdn: bigbreadth>=4 & liqbreadth<=1")
out += rep(X[big & (X.b_big_trd >= 4) & (X.b_spk_trd == 2)], "bigdn: bigbreadth>=4 & liqbreadth==2")
out += rep(X[big & (X.b_big_trd <= 2) & (X.b_spk_trd >= 3)], "bigdn: bigbreadth<=2 & liqbreadth>=3")
out += rep(X[big & (X.b_big_trd <= 2) & (X.b_spk_trd <= 1)], "bigdn: bigbreadth<=2 & liqbreadth<=1")
out += rep(X[big & (X.b_big_trd >= 6)], "bigdn: bigbreadth>=6 (any liq)")
out += rep(X[big & (X.b_big_trd >= 6) & (X.b_spk_trd >= 3)], "bigdn: bigbreadth>=6 & liqb>=3")
out += rep(X[big & (X.b_big_trd >= 6) & (X.b_spk_trd < 3)], "bigdn: bigbreadth>=6 & liqb<3")
print(pd.DataFrame(out).to_string(index=False))

print("\n--- own liq spike not required: any tradable symbol's down bar (rz<=-2) when liq breadth >= 3 ---")
out = []
out += rep(X[(X.rz <= -2) & (X.b_spk_trd >= 3)], "rz<=-2 & liqb_trd>=3 (own spike not required)")
out += rep(X[(X.rz <= -2) & (X.b_spk_trd >= 3) & X.spike], "  .. own spike")
out += rep(X[(X.rz <= -2) & (X.b_spk_trd >= 3) & ~X.spike], "  .. no own spike")
out += rep(X[(X.rz <= -3) & (X.b_spk_all >= 4)], "rz<=-3 & liqb_ALL>=4")
out += rep(X[(X.rz <= -3) & (X.b_spk_all >= 6)], "rz<=-3 & liqb_ALL>=6")
out += rep(X[(X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3)], "rz<=-3 & BTC spike & BTC rz<=-3")
out += rep(X[(X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3) & ~X.maj], "  .. alts only")
out += rep(X[(X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3) & X.maj], "  .. majors only")
out += rep(X[(X.rz <= -3) & ~X.btc_spike & (X.btc_rz <= -3)], "rz<=-3 & BTC rz<=-3 but NO BTC liq spike")
print(pd.DataFrame(out).to_string(index=False))
