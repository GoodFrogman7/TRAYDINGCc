import pandas as pd
from harness import *
from protos import *
rows=[]
s = LiqFlush()
for hold in (6, 12, 24):
    s.max_hold = hold
    for sa in (2.0, 3.0, 4.0):
        rows.append(line(run(s, {"stop_atr": sa}), f"liq z3 q99 hold{hold} stop{sa}"))
s.max_hold = 12
rows.append(line(run(s, {}, delay=1), "liq default DELAY+1"))
rows.append(line(run(s, {"z": 2.0}), "liq z2"))
rows.append(line(run(s, {"z": 4.0}), "liq z4"))
rows.append(line(run(s, {"liq_q": 0.95}), "liq q95"))
rows.append(line(run(s, {"sides": "both"}), "liq both sides"))
show(rows)
rows=[]
s = Capitulation()
for hold in (6, 12, 24):
    s.max_hold = hold
    for sa in (2.0, 3.0, 4.0):
        rows.append(line(run(s, {"stop_atr": sa}), f"cap k6 z4 hold{hold} stop{sa}"))
s.max_hold = 12
rows.append(line(run(s, {}, delay=1), "cap default DELAY+1"))
rows.append(line(run(s, {"z": 3.0}), "cap z3"))
rows.append(line(run(s, {"z": 5.0}), "cap z5"))
rows.append(line(run(s, {"k": 3}), "cap k3"))
rows.append(line(run(s, {"k": 12}), "cap k12"))
show(rows)
