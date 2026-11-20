"""H10: resting limit ('stink bid') k*ATR away from the last close, working for ONE bar.
Fill model = engine's: buy fills at L if next bar's low < L*(1-1bp) (at the open if it gaps below L).
Returns are measured from the FILL price L: to the close of the fill bar (c0), and to the open h bars later."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel2.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
for c in ("open","high","low","close"):
    p[f"n_{c}"] = g[c].shift(-1)          # LABEL: next bar (the fill bar)
for h in (1,2,4,8,12,24):
    p[f"o_{h}"] = g["open"].shift(-(1+h)) # LABEL: open h bars after the fill bar opens
p["low_next4"] = g["low"].transform(lambda s: s.shift(-2)[::-1].rolling(4, min_periods=1).min()[::-1])
p["high_next4"] = g["high"].transform(lambda s: s.shift(-2)[::-1].rolling(4, min_periods=1).max()[::-1])
t = p[p.tradable & ~p.bar_missing & p.atr24.notna()].copy()
rows=[]
for side in (1,-1):
    for k in (1.0,1.5,2.0,3.0,4.0):
        L = t.close - side*k*t.atr24
        if side==1:
            gap = t.n_open <= L; fill = gap | (t.n_low < L*(1-1e-4)); px = np.where(gap, t.n_open, L)
        else:
            gap = t.n_open >= L; fill = gap | (t.n_high > L*(1+1e-4)); px = np.where(gap, t.n_open, L)
        ev = t[fill].copy(); px = pd.Series(px, index=t.index)[fill]
        d = dict(side="buy" if side==1 else "sell", k=k, n=len(ev), days=ev.time.dt.floor("D").nunique(), fill_rate=fill.mean()*100)
        r0 = side*(ev.n_close/px-1)
        day = ev.time.dt.floor("D")
        d["c0_bps"] = r0.mean()*1e4; d["c0_med"] = r0.median()*1e4; d["c0_hit"] = (r0>0).mean(); d["c0_t"] = cluster_t(r0, day)
        d["c0_N"] = (r0/ev.atrp).mean()
        for h in (1,4,12):
            r = side*(ev[f"o_{h}"]/px-1); d[f"o{h}_bps"] = r.mean()*1e4; d[f"o{h}_N"] = (r/ev.atrp).mean(); d[f"o{h}_t"] = cluster_t(r/ev.atrp, day)
        for y in (2022,2023,2024):
            m = ev.year==y; d[f"N4_{y}"] = (side*(ev.loc[m,"o_4"]/px[m]-1)/ev.loc[m,"atrp"]).mean()
        m = ev.major; d["N4_maj"] = (side*(ev.loc[m,"o_4"]/px[m]-1)/ev.loc[m,"atrp"]).mean()
        d["worst_c0_N"] = (r0/ev.atrp).min(); d["p05_c0_N"] = (r0/ev.atrp).quantile(.05)
        rows.append(d)
with pd.option_context("display.width", 330, "display.float_format", lambda v: f"{v:,.2f}"):
    print(pd.DataFrame(rows).to_string(index=False))
