"""Neighbourhood + stress for the remaining candidates (design window, real engine)."""
from engine_check import *
import strats as S, strats2 as S2
from e06_final import Late
from desk.engine.core import Costs
rows = []
def add(st, lab, costs=None):
    r = check(st, label=lab, costs=costs); t = r["tdf"]
    if len(t) > 2:
        r["row"]["tR"] = round(t.r.mean() / t.r.std() * np.sqrt(len(t)), 2)
        d = t.groupby(pd.to_datetime(t.entry_time).dt.floor("D")).r.sum()
        r["row"]["days"] = len(d); r["row"]["tDay"] = round(d.mean() / d.std() * np.sqrt(len(d)), 2)
    rows.append(r); return r
print("### cascade grid z x k (stop 3 ATR, hold 36, market)")
for z in (1.5, 2.0, 2.5):
    for k in (2, 3, 4):
        add(S2.BreadthDiscount(max_hold=36, z=z, zb=z, k=k), f"cascade z=zb={z} k={k}")
table(rows); rows.clear()
print("### solo deep discount: z<=-2 & pm8<=-5bp, first in 24 bars")
d = lambda **kw: S.Variant("disc", "first", "disc_first", 36, **{"z": 2.0, **kw})
add(d(), "solo z2 floor5 first"); add(Late(d()), "solo LATE"); add(d(), "solo fees x2", costs=Costs(fee_mult=2.0))
add(d(floor_bp=3.0), "solo floor3"); add(d(floor_bp=8.0), "solo floor8"); add(d(floor_bp=0.0), "solo floor0")
table(rows); rows.clear()
print("### flush basket: breadth only, every tradable symbol, first in 24 bars, hold 48")
b = lambda hold=48, **kw: S2.BreadthDiscount(max_hold=hold, **{"k": 3, "who": "breadth_only", "mode": "first", **kw})
add(b(), "basket z2 k3"); add(Late(b()), "basket LATE"); add(b(), "basket fees x2", costs=Costs(fee_mult=2.0))
add(b(k=2), "basket k2"); add(b(k=4), "basket k4"); add(b(hold=24), "basket hold24"); add(b(hold=72), "basket hold72")
add(b(zb=1.5), "basket zb1.5 k3"); add(b(zb=2.5), "basket zb2.5 k3"); add(b(stop_atr=4.0), "basket stop4"); add(b(stop_atr=2.5), "basket stop2.5")
table(rows)
