"""Baselines: unconditional drift, slippage levels, 1-bar autocorrelation (bid/ask bounce check)."""
import numpy as np, pandas as pd
from lib import *
from desk.engine import costs

data = load()
p = panel(data)
p.to_pickle("/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel.pkl")
t = p[p.tradable]
print("tradable rows", len(t), "symbols", t.sym.nunique())
print("\nunconditional fwd (bps), tradable rows, by year")
print((t.groupby("year")[["fwd_1","fwd_4","fwd_12","fwd_24","fwd_48"]].mean()*1e4).round(2))
print((t.groupby("major")[["fwd_1","fwd_4","fwd_12","fwd_24","fwd_48"]].mean()*1e4).round(2))

# slippage levels the engine will charge
rows=[]
for s, df in data.items():
    sl = costs.slip_series(df)
    tm = store.tradable_mask(s, df.index)
    if tm.sum()==0: continue
    rows.append((s, sl[tm].median(), sl[tm].quantile(.9), (df.volume[tm]==0).mean(), (df.close*df.volume)[tm].median()))
print(pd.DataFrame(rows, columns=["sym","slip_med_bps","slip_p90","zero_vol_share","usd_vol_med"]).sort_values("slip_med_bps").round(2).to_string(index=False))

# 1-bar autocorrelation of close-to-close vs open-to-open returns (bounce diagnostic)
print("\nlag-1 autocorr of hourly returns (tradable bars)")
rows=[]
for s, g in t.groupby("sym"):
    r = g.ret1
    rows.append((s, r.autocorr(1), len(g)))
print(pd.DataFrame(rows, columns=["sym","ac1","n"]).round(3).to_string(index=False))
