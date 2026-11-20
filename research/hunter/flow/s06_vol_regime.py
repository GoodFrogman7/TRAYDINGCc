"""H4 compression->expansion with volume; H5 volume climax at range extremes; H1e mirror (BTC short squeeze)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz})
for s, f in P.items():
    f["rvr"] = f["rv24"] / f["rv720"]                      # short vs long realised vol
    f["rvr_prev"] = f["rvr"].shift(1)
    f["bbw_rank_prev"] = f["bbw_rank"].shift(1)
    f["rv24_rank_prev"] = f["rv24"].rolling(720, min_periods=360).rank(pct=True).shift(1)
    f["up48"] = f["close"] > f["high"].shift(1).rolling(48).max()
    f["dn48"] = f["close"] < f["low"].shift(1).rolling(48).min()
    f["up168"] = f["close"] > f["hh168"]
    f["dn168"] = f["close"] < f["ll168"]
    f["low168"] = f["low"] < f["ll168"]
    f["high168"] = f["high"] > f["hh168"]
X = F.stack(P).join(bs, on="time")
X = X[X.tradable & ~X.miss].copy()

def rep(E, name, d, hs=(4, 12, 24, 48, 72)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r))
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        out.append(s)
    return out

print("=== H4: compression (prev-bar 48h BB width rank <= q) then 48h-range breakout close ===")
out = []
for q in (0.15, 0.3):
    comp = X.bbw_rank_prev <= q
    out += rep(X[comp & X.up48], f"comp<={q} break UP -> LONG", 1)
    out += rep(X[comp & X.dn48], f"comp<={q} break DN -> SHORT", -1)
    out += rep(X[comp & X.up48 & (X.vol_rel >= 3)], f"comp<={q} break UP + vol>=3x -> LONG", 1)
    out += rep(X[comp & X.dn48 & (X.vol_rel >= 3)], f"comp<={q} break DN + vol>=3x -> SHORT", -1)
out += rep(X[(X.bbw_rank_prev > 0.5) & X.up48], "NO compression break UP -> LONG", 1)
out += rep(X[(X.bbw_rank_prev > 0.5) & X.dn48], "NO compression break DN -> SHORT", -1)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== H5: volume climax at a 168h extreme (new 7d low/high intrabar, vol_rel>=5) ===")
out = []
out += rep(X[X.low168 & (X.vol_rel >= 5)], "new 7d low + vol>=5x -> LONG", 1)
out += rep(X[X.low168 & (X.vol_rel >= 5) & (X.clpos >= 0.5)], "new 7d low + vol>=5x + close in upper half -> LONG", 1)
out += rep(X[X.low168 & (X.vol_rel >= 5) & (X.clpos < 0.25)], "new 7d low + vol>=5x + close near low -> LONG", 1)
out += rep(X[X.high168 & (X.vol_rel >= 5)], "new 7d high + vol>=5x -> SHORT", -1)
out += rep(X[X.high168 & (X.vol_rel >= 5) & (X.clpos <= 0.5)], "new 7d high + vol>=5x + close in lower half -> SHORT", -1)
out += rep(X[X.high168 & (X.vol_rel >= 5) & (X.clpos > 0.75)], "new 7d high + vol>=5x + close near high -> LONG(cont)", 1)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== H1e mirror: BTC SHORT-liquidation spike (BTC rz>=3 & liq spike), symbols with rz>=3 ===")
out = []
out += rep(X[(X.rz >= 3) & X.btc_spike & (X.btc_rz >= 3)], "squeeze -> SHORT(fade)", -1)
out += rep(X[(X.rz >= 3) & ~X.btc_spike & (X.btc_rz >= 3)], "BTC up no liq -> SHORT(fade)", -1)
print(pd.DataFrame(out).to_string(index=False))
