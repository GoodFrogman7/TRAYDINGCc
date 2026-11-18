"""Path statistics for the long-fade signals: how deep does price go against the entry before the snapback?
(MAE over the hold in ATR units -> what a k*ATR stop does to the edge)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
from desk.data import store
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
raw = store.load_design()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz})
for s, f in P.items():
    m = raw[s]["mark_close"]; mr = m / m.shift(1) - 1
    f["mrz"] = mr / mr.rolling(168, min_periods=100).std().shift(1)
    f["bbw_rank_prev"] = f["bbw_rank"].shift(1)
    f["dn48"] = f["close"] < f["low"].shift(1).rolling(48).min()
    if "half_spread_bps" in f:
        f["sp_rel"] = f["half_spread_bps"] / f["half_spread_bps"].rolling(168, min_periods=48).median().shift(1)
    f["ent"] = f["open"].shift(-1)
    f["stopdist_close"] = f["atr"] / f["close"]
X = F.stack(P).join(bs, on="time")
X = X[X.tradable & ~X.miss].copy()
sig = {
    "cascade": (X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3),
    "hotbrk": X.dn48 & (X.bbw_rank_prev > 0.5),
    "vacuum": (X.sp_rel >= 2) & (X.ret4 < -2 * X.atrp),
    "airpocket": (X.rz <= -3) & (X.vol_rel <= 4) & (X.mrz <= -3),
}
for nm, m in sig.items():
    E = X[m].copy()
    print(f"\n=== {nm}: n={len(E)}  ATR%/close median {E.atrp.median()*100:.2f}%  mean {E.atrp.mean()*100:.2f}%")
    for h in (12, 24):
        mae = -(E[f"mae{h}_lo"]) / E.atrp           # adverse excursion in ATR units (positive = against a long)
        mfe = (E[f"mfe{h}_hi"]) / E.atrp
        r = E[f"f{h}"] / E.atrp
        q = mae.quantile([.25, .5, .75, .9, .95]).round(2).to_dict()
        print(f" h={h}: MAE(ATR) quantiles {q} | MFE med {mfe.median():.2f} | mean fwd (ATR) {r.mean():.3f}")
        rows = []
        for k in (1.5, 2.5, 4.0, 6.0):
            hit = mae >= k
            # crude: stopped trades lose k ATR, others earn the time-exit return
            pay = np.where(hit, -k, r)
            rows.append(dict(stop_atr=k, stopped=round(hit.mean(), 3), mean_atr=round(np.nanmean(pay), 3), mean_R=round(np.nanmean(pay) / k, 3),
                             unstopped_mean_atr=round(r[~hit].mean(), 3), ret_of_stopped_if_held=round(r[hit].mean(), 3)))
        print(pd.DataFrame(rows).to_string(index=False))
