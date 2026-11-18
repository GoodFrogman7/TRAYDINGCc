import pandas as pd, numpy as np
from harness import *
from protos3 import *
from desk.engine.core import Risk, Costs
s = PremiumFade2()
rows=[]
base = run(s, {})
rows.append(line(base, "both .3% hold8 stop3 (base)"))
rows.append(line(run(s, {}, delay=1), "base DELAY+1"))
rows.append(line(run(s, {}, costs=Costs(fee_mult=2.0)), "base FEES x2"))
rows.append(line(run(s, {}, costs=Costs(slip_mult=2.0)), "base SLIP x2"))
rows.append(line(run(s, {}, costs=Costs(funding_mult=0.0)), "base NO FUNDING"))
rows.append(line(run(s, {"skip": ("PF_INJUSD",)}), "base ex-INJ"))
rows.append(line(run(s, {"skip": ("PF_INJUSD","PF_SOLUSD")}), "base ex-INJ ex-SOL"))
for tp in (1.5, 2.5):
    rows.append(line(run(s, {"tp_atr": tp}), f"tp {tp} atr"))
rows.append(line(run(s, {"exit_prem": 0.001}), "exit when |prem|<0.1%"))
for la in (0.5, 1.0):
    s.valid_bars = 3
    rows.append(line(run(s, {"lim_atr": la}), f"limit {la} atr away, valid 3"))
s.valid_bars = 1
for pr in (0.0025, 0.0035, 0.004):
    rows.append(line(run(s, {"prem": pr}), f"prem {pr}"))
for hold in (4, 12, 24):
    s.max_hold = hold
    rows.append(line(run(s, {}), f"hold {hold}"))
s.max_hold = 8
for sa in (2.0, 4.0, 5.0):
    rows.append(line(run(s, {"stop_atr": sa}), f"stop {sa}"))
show(rows)
t = trades_df(base)
print("\ntrades per symbol / R:"); print(t.groupby("symbol").agg(n=("r","size"), R=("r","sum"), bps=("net_bps","mean")).sort_values("n", ascending=False).round(2).head(15).to_string())
print("\ndistinct entry days:", t.entry_time.dt.floor("D").nunique(), " months with trades:", t.entry_time.dt.strftime("%Y-%m").nunique())
m = t.groupby(t.entry_time.dt.strftime("%Y-%m")).agg(n=("r","size"), R=("r","sum")).round(2)
print(m.T.to_string())
print("\nby side & year:"); print(t.groupby(["side","year"]).agg(n=("r","size"), R=("r","sum"), avgR=("r","mean"), win=("r", lambda x:(x>0).mean()), bps=("ret_bps","mean"), fund=("funding","sum")).round(2).to_string())
print("\nexit reasons:", base["summary"]["exit_reasons"], " funding usd total (neg = received):", round(base["summary"]["funding_usd"],1), " fees:", round(base["summary"]["fees_usd"],1), "gross:", round(base["summary"]["gross_pnl_usd"],1))
print("R distribution:", t.r.describe().round(2).to_dict())
