"""Robustness: are the snapbacks real or last-trade print artefacts? Re-measure forward returns on MARK prices."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
from desk.data import store
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

P = F.panel()
raw = store.load_design()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz, "btc_volrel": btc.vol_rel})
for s, f in P.items():
    m = raw[s]["mark_close"]
    f["mark"] = m
    f["disc"] = f["close"] / m - 1                       # last trade vs mark at the signal close
    for h in (1, 4, 12, 24):
        f[f"m{h}"] = m.shift(-h) / m - 1                 # mark-to-mark forward return from the signal close
    f["mr1"] = m / m.shift(1) - 1
    f["mrz"] = f["mr1"] / f["mr1"].rolling(168, min_periods=100).std().shift(1)
    f["bbw_rank_prev"] = f["bbw_rank"].shift(1)
    f["dn48"] = f["close"] < f["low"].shift(1).rolling(48).min()
    if "half_spread_bps" in f:
        f["sp_rel"] = f["half_spread_bps"] / f["half_spread_bps"].rolling(168, min_periods=48).median().shift(1)
X = F.stack(P).join(bs, on="time")
X = X[X.tradable & ~X.miss].copy()
sig = {
    "cascade": (X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3),
    "hotbrk": X.dn48 & (X.bbw_rank_prev > 0.5),
    "vacuum": (X.sp_rel >= 2) & (X.ret4 < -2 * X.atrp),
    "airpocket<=4": (X.rz <= -3) & (X.vol_rel <= 4),
    "airpocket<=1.5": (X.rz <= -3) & (X.vol_rel <= 1.5),
    "airpocket<=4 & mark confirms (mrz<=-3)": (X.rz <= -3) & (X.vol_rel <= 4) & (X.mrz <= -3),
    "airpocket<=4 & mark NOT confirming": (X.rz <= -3) & (X.vol_rel <= 4) & (X.mrz > -2),
    "lowvol pump (rz>=3, vol_rel<=1.5)": (X.rz >= 3) & (X.vol_rel <= 1.5),
}
rows = []
for nm, m in sig.items():
    E = X[m]
    r = dict(sig=nm, n=len(E), disc_bps_mean=round(E.disc.mean() * 1e4, 1), disc_bps_med=round(E.disc.median() * 1e4, 1),
             mrz_med=round(E.mrz.median(), 2))
    for h in (1, 4, 12, 24):
        r[f"trade_f{h}"] = round(E[f"f{h}"].mean() * 1e4, 1)
        r[f"mark_m{h}"] = round(E[f"m{h}"].mean() * 1e4, 1)
    for y in (2022, 2023, 2024):
        r[f"mark12_{y}"] = round(E[E.year == y]["m12"].mean() * 1e4, 0)
    rows.append(r)
print(pd.DataFrame(rows).T.to_string())
