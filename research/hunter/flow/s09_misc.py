"""H7 thin-weekend move reversal; H8 BTC volume-surge lead -> alt catch-up; overlap between the long-capitulation signals."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz, "btc_volrel": btc.vol_rel})
for s, f in P.items():
    f["bbw_rank_prev"] = f["bbw_rank"].shift(1)
    f["dn48"] = f["close"] < f["low"].shift(1).rolling(48).min()
    if "half_spread_bps" in f:
        f["sp_rel"] = f["half_spread_bps"] / f["half_spread_bps"].rolling(168, min_periods=48).median().shift(1)
    # weekend move: at Sunday 21:00 bar close (22:00 UTC), return since Friday 22:00 UTC (48 bars)
    f["dow"] = f.index.dayofweek; f["hr"] = f.index.hour
    f["wk_ret"] = f["close"] / f["close"].shift(48) - 1
    f["wk_z"] = f["wk_ret"] / (f["sd168"] * np.sqrt(48))
    f["wkvol"] = f["usd_vol"].rolling(48).sum() / f["usd_vol"].rolling(168).sum().shift(48)   # weekend volume vs prior week
X = F.stack(P).join(bs, on="time")
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

print("=== H7 weekend reversal: Sunday 21:00 UTC bar, weekend move z ===")
W = X[(X.dow == 6) & (X.hr == 21)]
out = []
for z in (1.0, 1.5):
    out += rep(W[W.wk_z <= -z], f"weekend down z<=-{z} -> LONG", 1, hs=(12, 24, 48))
    out += rep(W[W.wk_z >= z], f"weekend up z>={z} -> SHORT", -1, hs=(12, 24, 48))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== H8 BTC surge lead: BTC rz>=3 & vol_rel>=3, alt lagging (alt rz < 1) -> LONG alt ; mirror ===")
A = X[~X.maj]
out = []
out += rep(A[(A.btc_rz >= 3) & (A.btc_volrel >= 3) & (A.rz < 1)], "BTC up surge, alt lag -> LONG", 1, hs=(1, 4, 12))
out += rep(A[(A.btc_rz <= -3) & (A.btc_volrel >= 3) & (A.rz > -1)], "BTC dn surge, alt lag -> SHORT", -1, hs=(1, 4, 12))
print(pd.DataFrame(out).to_string(index=False))

print("\n=== overlap of long-capitulation signals (tradable bars) ===")
s1 = (X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3)
s2 = X.dn48 & (X.bbw_rank_prev > 0.5)
s3 = (X.sp_rel >= 2) & (X.ret4 < -2 * X.atrp)
s4 = (X.rz <= -3) & (X.vol_rel <= 4)
S = pd.DataFrame({"cascade": s1, "hotbrk": s2, "vacuum": s3, "airpocket": s4})
print("counts", S.sum().to_dict())
print("pairwise share of row-signal that is also col-signal:")
print(pd.DataFrame({a: {b: round((S[a] & S[b]).sum() / max(S[a].sum(), 1), 2) for b in S} for a in S}).T)
X["nsig"] = S.sum(axis=1)
# each signal EXCLUDING bars where the cascade signal fires
out = []
out += rep(X[s2 & ~s1], "hotbrk excluding cascade", hs=(4, 12, 24))
out += rep(X[s3 & ~s1], "vacuum excluding cascade", hs=(4, 12, 24))
out += rep(X[s3 & ~s1 & ~s2], "vacuum excluding cascade & hotbrk", hs=(4, 12, 24))
out += rep(X[s4 & ~s1], "airpocket excluding cascade", hs=(4, 12, 24))
out += rep(X[s2 & ~s1 & ~s3 & (X.time >= "2023-07-01")], "hotbrk excl cascade & vacuum (2023-07+)", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))
