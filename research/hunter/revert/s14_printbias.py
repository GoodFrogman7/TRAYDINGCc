"""How much of the engine's premium-fade P&L comes from filling at a last print that sits away from the mark?"""
import pandas as pd, numpy as np
from harness import *
import protos2, protos3
from protos3 import *
s = PremiumFade2()
m = market()
base = run(s, {})
t = trades_df(base)
# entry bar = entry_time; the signal bar is the one before. favourable print bias = side * (mark - fillref)/mark
bias=[]
for _, r in t.iterrows():
    df = m.data[r.symbol]
    i = df.index.get_loc(r.entry_time) - 1
    c, mk = df["close"].iloc[i], df["mark_close"].iloc[i]
    bias.append(r.side * (mk / c - 1) * 1e4)   # >0: engine filled us better than the mark
t["bias_bps"] = bias
print("signed print-vs-mark advantage at entry (bps): mean %.1f median %.1f  | by side: %s" % (t.bias_bps.mean(), t.bias_bps.median(), t.groupby("side").bias_bps.mean().round(1).to_dict()))
print("corr(bias, net_bps) = %.2f" % t[["bias_bps","net_bps"]].corr().iloc[0,1])
rows=[line(base, "tol 0.30% (base)")]
for tol in (0.001, 0.0005):
    orig = protos2.print_ok
    f = lambda df, tol=tol: (df["close"]/df["mark_close"]-1).abs() <= tol
    protos3.print_ok = f
    rows.append(line(run(s, {}), f"tol {tol*100:.2f}%"))
    protos3.print_ok = orig
show(rows)
