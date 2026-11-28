from research.hunter.cross.bt import *
from research.hunter.cross.strats import *
from desk.engine.core import Costs
rows = []; S = RSLeader(); g = {"breadth_min": 0.5, "ma": 200}
for lab, p in [("gated L336 k2", {}), ("gated L168", {"L": 168}), ("gated L504", {"L": 504}), ("gated k1.5", {"stop_k": 1.5}), ("gated k3", {"stop_k": 3.0}), ("gated top1", {"top": 1}), ("gated top3", {"top": 3})]:
    rows.append(report(S, {**g, **p}, lab)["row"])
rows.append(report(Delayed(S), g, "gated, 1 bar late")["row"])
rows.append(report(S, g, "gated, fees x2", costs=Costs(fee_mult=2.0))["row"])
table(rows)
