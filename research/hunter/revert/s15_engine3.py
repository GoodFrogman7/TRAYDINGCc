import pandas as pd
from harness import *
from protos4 import *
from desk.engine.core import Risk, Costs
rows=[]
s = Cascade()
rows.append(line(run(s, {}), "cascade z4 zb3 hold12 stop4 (base)"))
rows.append(line(run(s, {}, delay=1), "cascade DELAY+1"))
rows.append(line(run(s, {}, costs=Costs(fee_mult=2.0)), "cascade FEES x2"))
rows.append(line(run(s, {"stop_atr": 3.0}), "cascade stop3"))
rows.append(line(run(s, {"stop_atr": 5.0}), "cascade stop5"))
rows.append(line(run(s, {"z": 3.0}), "cascade z3"))
rows.append(line(run(s, {"z": 5.0}), "cascade z5"))
rows.append(line(run(s, {"zb": 2.0}), "cascade zb2"))
rows.append(line(run(s, {"zb": 4.0}), "cascade zb4"))
s.max_hold = 24; rows.append(line(run(s, {}), "cascade hold24")); s.max_hold = 6; rows.append(line(run(s, {}), "cascade hold6")); s.max_hold = 12
s.valid_bars = 3
rows.append(line(run(s, {"lim_atr": 1.0}), "cascade LIMIT 1atr below, valid3"))
rows.append(line(run(s, {"lim_atr": 1.0, "tp_atr": 2.0}), "cascade LIMIT 1atr, tp2"))
s.valid_bars = 1
show(rows)
rows=[]
s = OIWipe()
rows.append(line(run(s, {}), "oiwipe k3 z3 q01 hold12 stop4 (base)"))
rows.append(line(run(s, {}, delay=1), "oiwipe DELAY+1"))
rows.append(line(run(s, {"stop_atr": 3.0}), "oiwipe stop3"))
rows.append(line(run(s, {"z": 2.0}), "oiwipe z2"))
rows.append(line(run(s, {"q": 0.02}), "oiwipe q02"))
rows.append(line(run(s, {"k": 1}), "oiwipe k1"))
rows.append(line(run(s, {"k": 6}), "oiwipe k6"))
show(rows)
rows=[]
s = FlushBid()
rows.append(line(run(s, {}), "flushbid z2 liq1 lim1 stop3 tp2 (base)"))
rows.append(line(run(s, {"lim_atr": 0.5}), "flushbid lim0.5"))
rows.append(line(run(s, {"lim_atr": 1.5}), "flushbid lim1.5"))
rows.append(line(run(s, {"tp_atr": 0.0}), "flushbid no tp"))
rows.append(line(run(s, {"tp_atr": 1.0}), "flushbid tp1"))
rows.append(line(run(s, {"stop_atr": 2.0}), "flushbid stop2"))
rows.append(line(run(s, {"stop_atr": 4.0}), "flushbid stop4"))
rows.append(line(run(s, {"z": 3.0, "liq_mult": 2.0}), "flushbid z3 liq2"))
show(rows)
