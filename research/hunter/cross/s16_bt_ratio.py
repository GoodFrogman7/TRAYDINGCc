from research.hunter.cross.bt import *
from research.hunter.cross.strats import *
from desk.engine.core import Costs
rows = []; S = RatioBreak()
for lab, p in [("N336 ma480 k2.5 both gated", {}), ("long only", {"sides": "long"}), ("short only", {"sides": "short"}), ("ungated both", {"gate": False}),
               ("N168", {"N": 168}), ("N504", {"N": 504}), ("stop_k 2", {"stop_k": 2.0}), ("stop_k 3", {"stop_k": 3.0}), ("ma 200", {"ma": 200})]:
    rows.append(report(S, p, lab)["row"])
rows.append(report(Delayed(S), {}, "default, 1 bar late")["row"])
rows.append(report(S, {}, "default, fees x2", costs=Costs(fee_mult=2.0))["row"])
table(rows)
