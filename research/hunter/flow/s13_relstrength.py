"""H9: 'stress-tested bid' - BTC dumps on a volume surge, an alt refuses to follow. Does the alt outperform afterwards?"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 500)

P = F.panel()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz, "btc_volrel": btc.vol_rel,
                   "btc_f4": btc.f4, "btc_f12": btc.f12, "btc_f24": btc.f24, "btc_ret4": btc.ret4, "btc_atrp": btc.atrp})
X = F.stack(P).join(bs, on="time")
X = X[X.tradable & ~X.miss].copy()
A = X[~X.maj].copy()
A["path12"] = -(A["mae12_lo"]) / A.atrp

def rep(E, name, d=1, hs=(1, 4, 12, 24, 48)):
    out = []
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{name} h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            gg = r[E.year == y]; s[f"y{y}"] = f"{gg.mean()*1e4:.0f}/{len(gg)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        s["fwd_atr"] = round((r / E.atrp).mean(), 3)
        out.append(s)
    return out

out = []
dump = (A.btc_rz <= -3) & (A.btc_volrel >= 3)
out += rep(A[dump & (A.rz > -1)], "BTC dump(z<=-3,vol>=3x), alt held (rz>-1) LONG")
out += rep(A[dump & (A.rz <= -1) & (A.rz > -3)], "BTC dump, alt fell some (-3<rz<=-1) LONG")
out += rep(A[dump & (A.rz <= -3)], "BTC dump, alt fell hard (rz<=-3) LONG")
print(pd.DataFrame(out).to_string(index=False))
print("\nBTC's own forward return after its dump bar (bps): f4 %.1f f12 %.1f f24 %.1f  n=%d" % tuple(
    list(btc[(btc.rz <= -3) & (btc.vol_rel >= 3)][["f4", "f12", "f24"]].mean() * 1e4) + [int(((btc.rz <= -3) & (btc.vol_rel >= 3)).sum())]))
E = A[dump & (A.rz > -1)]
print("alt-minus-BTC forward (bps): f4 %.1f f12 %.1f f24 %.1f" % ((E.f4 - E.btc_f4).mean() * 1e4, (E.f12 - E.btc_f12).mean() * 1e4, (E.f24 - E.btc_f24).mean() * 1e4))
print("alt held events: ATR%% median %.2f, MAE12 (ATR) quantiles %s" % (E.atrp.median() * 100, E.path12.quantile([.25, .5, .75, .9]).round(2).to_dict()))
print(E.groupby("sym").agg(n=("f12", "size"), f12=("f12", lambda s: round(s.mean() * 1e4, 0))).sort_values("n", ascending=False).head(12).T)

print("\n--- robustness: thresholds ---")
out = []
for zb, vb, za in ((-2.5, 3, -1), (-3, 3, -0.5), (-3, 2, -1), (-3.5, 3, -1), (-3, 3, 0)):
    m = (A.btc_rz <= zb) & (A.btc_volrel >= vb) & (A.rz > za)
    out += rep(A[m], f"BTC z<={zb} vol>={vb}x alt rz>{za}", hs=(4, 12, 24))
out += rep(A[dump & (A.rz > -1) & A.btc_spike], "alt held & BTC liq spike", hs=(4, 12, 24))
out += rep(A[dump & (A.rz > -1) & ~A.btc_spike], "alt held & NO BTC liq spike", hs=(4, 12, 24))
print(pd.DataFrame(out).to_string(index=False))
print("\nper-day detail (alt held):")
g = E.groupby(E.time.dt.date).agg(n=("f12", "size"), f12=("f12", "mean"), f24=("f24", "mean"))
print("days", len(g), "day-level mean f12 bps", round(g.f12.mean() * 1e4, 1), "hit", round((g.f12 > 0).mean(), 2), "median", round(g.f12.median() * 1e4, 1))
