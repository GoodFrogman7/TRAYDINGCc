import pandas as pd
from harness import *
from protos2 import *
from desk.engine.core import Risk
rows=[]
s = Capitulation()
for hold in (12, 24):
    s.max_hold = hold
    for sa in (2.0, 3.0, 4.0):
        rows.append(line(run(s, {"stop_atr": sa}), f"cap k6 z5 hold{hold} stop{sa}"))
s.max_hold = 24
rows.append(line(run(s, {}, delay=1), "cap default DELAY+1"))
rows.append(line(run(s, {}, risk=Risk(guardian=False)), "cap default NO GUARDIAN"))
rows.append(line(run(s, {"z": 4.0}), "cap z4"))
rows.append(line(run(s, {"z": 6.0}), "cap z6"))
rows.append(line(run(s, {"top_n": 3}), "cap top3"))
rows.append(line(run(s, {"tp_atr": 3.0}), "cap tp3"))
show(rows)
rows=[]
s = LiqFlush()
for hold in (12, 24):
    s.max_hold = hold
    for sa in (2.0, 3.0, 4.0):
        rows.append(line(run(s, {"stop_atr": sa}), f"liq2 z3 hold{hold} stop{sa}"))
s.max_hold = 12
rows.append(line(run(s, {}, delay=1), "liq default DELAY+1"))
rows.append(line(run(s, {}, risk=Risk(guardian=False)), "liq default NO GUARDIAN"))
rows.append(line(run(s, {"tp_atr": 3.0}), "liq tp3"))
show(rows)
rows=[]
s = PremiumFade()
for hold in (4, 8, 12):
    s.max_hold = hold
    for sa in (2.0, 3.0, 4.0):
        rows.append(line(run(s, {"stop_atr": sa}), f"prem short .3% hold{hold} stop{sa}"))
s.max_hold = 8
rows.append(line(run(s, {}, delay=1), "prem short DELAY+1"))
rows.append(line(run(s, {}, risk=Risk(guardian=False)), "prem short NO GUARDIAN"))
rows.append(line(run(s, {"prem": 0.002}), "prem short .2%"))
rows.append(line(run(s, {"prem": 0.004}), "prem short .4%"))
rows.append(line(run(s, {"sides": "long"}), "prem LONG .3%"))
rows.append(line(run(s, {"sides": "both"}), "prem both .3%"))
show(rows)
