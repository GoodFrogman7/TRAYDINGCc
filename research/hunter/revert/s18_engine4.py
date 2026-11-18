import pandas as pd
from harness import *
from protos5 import *
from desk.engine.core import Risk, Costs
rows=[]
s = CrashBid()
base = run(s, {})
rows.append(line(base, "crashbid er>.35 lim3 stop4 hold12 (base)"))
rows.append(line(run(s, {}, costs=Costs(fee_mult=2.0)), "FEES x2"))
rows.append(line(run(s, {}, risk=Risk(guardian=False)), "NO GUARDIAN"))
for st in (3.0, 5.0, 6.0):
    rows.append(line(run(s, {"stop_atr": st}), f"stop {st}"))
for la in (2.0, 2.5, 4.0):
    rows.append(line(run(s, {"lim_atr": la}), f"lim {la}"))
for er in (0.25, 0.30, 0.45):
    rows.append(line(run(s, {"er_min": er}), f"er_min {er}"))
rows.append(line(run(s, {"er_min": 0.0}), "no regime filter (er_min 0)"))
rows.append(line(run(s, {"trend": "up"}), "uptrend only"))
rows.append(line(run(s, {"trend": "down"}), "downtrend only"))
rows.append(line(run(s, {"tp_atr": 3.0}), "tp 3 atr"))
for hold in (6, 24):
    s.max_hold = hold; rows.append(line(run(s, {}), f"hold {hold}"))
s.max_hold = 12
show(rows)
t = trades_df(base)
print(base["summary"]["exit_reasons"], "maker share", base["summary"]["maker_entry_share"])
print(t.groupby("symbol").agg(n=("r","size"), R=("r","sum")).sort_values("n", ascending=False).round(2).head(12).T.to_string())
print("distinct entry days:", t.entry_time.dt.floor("D").nunique())
print("same-bar stops (bars_held<=1 & stop):", int(((t.reason=="stop")&(t.bars_held<=1)).sum()))
print("R dist:", t.r.describe().round(2).to_dict())
