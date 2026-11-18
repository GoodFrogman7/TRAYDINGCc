import pandas as pd
from harness import *
from protos import *
from desk.engine.core import Risk
rows=[]
s = LiqFlush(); s.max_hold = 12
r = run(s, {}); print(r["summary"]["exit_reasons"]); rows.append(line(r, "liq default"))
r = run(s, {}, risk=Risk(guardian=False)); print(r["summary"]["exit_reasons"]); rows.append(line(r, "liq default NO GUARDIAN"))
r = run(s, {"stop_atr": 10.0}, risk=Risk(guardian=False)); print(r["summary"]["exit_reasons"]); rows.append(line(r, "liq stop10 NO GUARDIAN"))
r = run(s, {"stop_atr": 6.0}); print(r["summary"]["exit_reasons"]); rows.append(line(r, "liq stop6"))
s = Capitulation(); s.max_hold = 12
r = run(s, {}); print(r["summary"]["exit_reasons"]); rows.append(line(r, "cap default"))
r = run(s, {}, risk=Risk(guardian=False)); print(r["summary"]["exit_reasons"]); rows.append(line(r, "cap default NO GUARDIAN"))
r = run(s, {"stop_atr": 10.0}, risk=Risk(guardian=False)); rows.append(line(r, "cap stop10 NO GUARDIAN"))
show(rows)
t = trades_df(run(LiqFlush(), {}, risk=Risk(guardian=False)))
print(t.groupby("reason")[["r","ret_bps","net_bps"]].agg(["count","mean"]))
print(t[["r","ret_bps"]].describe())
