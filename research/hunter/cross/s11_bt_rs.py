from research.hunter.cross.bt import *
from research.hunter.cross.strats import *
from desk.engine.core import Costs

rows = []
S = RSLeader()
for lab, p in [("L336 top2 abs k2 exit5", {}), ("no abs filter", {"abs_filter": False}), ("L168", {"L": 168}), ("L504", {"L": 504}),
               ("top1", {"top": 1}), ("top3", {"top": 3}), ("stop_k 1.5", {"stop_k": 1.5}), ("stop_k 3", {"stop_k": 3.0}),
               ("exit_rank 3", {"exit_rank": 3}), ("exit_rank 7", {"exit_rank": 7}),
               ("breadth>=0.5 (480)", {"breadth_min": 0.5}), ("breadth>=0.5 (200)", {"breadth_min": 0.5, "ma": 200}),
               ("long+short mirrored", {"short": True}), ("long+short, breadth 0.5", {"short": True, "breadth_min": 0.5})]:
    rows.append(report(S, p, lab)["row"])
rows.append(report(Delayed(S), {}, "default, 1 bar late")["row"])
rows.append(report(S, {}, "default, fees x2", costs=Costs(fee_mult=2.0))["row"])
table(rows)
