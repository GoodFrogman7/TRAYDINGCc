from research.hunter.cross.bt import *
from research.hunter.cross.strats import *
from desk.engine.core import Costs

print("== flush bounce ==")
rows = []; S = FlushBounce()
for lab, p in [("k4 liq5 stop4 all", {}), ("alts only", {"who": "alts"}), ("majors", {"who": "majors"}), ("k3", {"k": 3.0}), ("k5", {"k": 5.0}), ("no liq filter", {"liq_mult": 0.0}),
               ("liq 3x", {"liq_mult": 3.0}), ("stop 3", {"stop_atr": 3.0}), ("stop 6", {"stop_atr": 6.0})]:
    rows.append(report(S, p, lab)["row"])
rows.append(report(Delayed(S), {}, "default, 1 bar late")["row"])
rows.append(report(S, {}, "default, fees x2", costs=Costs(fee_mult=2.0))["row"])
class FB24(FlushBounce):
    max_hold = 24
class FB6(FlushBounce):
    max_hold = 6
rows.append(report(FB6(), {}, "hold 6")["row"]); rows.append(report(FB24(), {}, "hold 24")["row"])
table(rows)

print("\n== idio breakout ==")
rows = []; S = IdioBreakout()
for lab, p in [("k3 stop2 br0.5/200", {}), ("k2", {"k": 2.0}), ("no breadth gate", {"breadth_min": 0.0}), ("stop_k 3", {"stop_k": 3.0}), ("ma 480", {"ma": 480})]:
    rows.append(report(S, p, lab)["row"])
rows.append(report(Delayed(S), {}, "default, 1 bar late")["row"])
table(rows)

print("\n== weekend alts sleeve ==")
rows = []; S = WeekendAlts()
for lab, p in [("n_alt3 thr0.5% stop5", {}), ("n_alt 2", {"n_alt": 2}), ("n_alt 5", {"n_alt": 5}), ("thr 0", {"thr": 0.0}), ("thr 1%", {"thr": 0.01}), ("stop 4", {"stop_atr": 4.0}), ("stop 6", {"stop_atr": 6.0})]:
    rows.append(report(S, p, lab)["row"])
rows.append(report(Delayed(S), {}, "default, 1 bar late")["row"])
rows.append(report(S, {}, "default, fees x2", costs=Costs(fee_mult=2.0))["row"])
table(rows)
