"""(i) spring / upthrust: bar pierces the prior N-bar extreme and closes back inside (stop-run reversal).
(ii) stink bids only in ranging, quiet conditions. Forward returns on MARK prices, ATR units."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel3.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
for n in (24, 72):
    p[f"lo{n}"] = g["low"].transform(lambda s: s.shift(1).rolling(n, min_periods=n).min())
    p[f"hi{n}"] = g["high"].transform(lambda s: s.shift(1).rolling(n, min_periods=n).max())
p["pierce_lo"] = (p.lo72 - p.low) / p.atr24_prev
p["pierce_hi"] = (p.high - p.hi72) / p.atr24_prev
for c in ("open","high","low","close"):
    p[f"n_{c}"] = g[c].shift(-1)
p["o_4"] = g["open"].shift(-5); p["o_12"] = g["open"].shift(-13)
t = p[p.tradable & ~p.bar_missing & p.mark_close.notna() & ((p.close/p.mark_close-1).abs()<=0.003)].copy()
def tab(rules, hy=12):
    rows=[]
    for lab, mm, sg in rules:
        ev = t[mm]; day = ev.time.dt.floor("D")
        d = dict(rule=lab, n=len(ev), days=day.nunique(), bps4=(ev.M4*sg).mean()*1e4, bps12=(ev.M12*sg).mean()*1e4)
        for h in (1,4,12,24):
            x = (ev[f"NM{h}"]*sg); d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, day)
        d[f"N{hy}_dly"] = (ev[f"NM{hy}_d"]*sg).mean(); d["hit"] = ((ev[f"M{hy}"]*sg)>0).mean()
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,f"NM{hy}"]*sg).mean()
        rows.append(d)
    with pd.option_context("display.width", 350, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
print("## spring (pierce prior 72h low by >=x ATR, close back above it) long ; upthrust short")
tab([
 ("spring pierce>0.5atr", (t.pierce_lo>0.5)&(t.close>t.lo72), 1),
 ("spring pierce>1atr", (t.pierce_lo>1.0)&(t.close>t.lo72), 1),
 ("spring pierce>1atr & vrel>3", (t.pierce_lo>1.0)&(t.close>t.lo72)&(t.vrel>3), 1),
 ("break: close below 72h low by >1atr (no reclaim) long", ((t.lo72-t.close)/t.atr24_prev>1.0), 1),
 ("upthrust pierce>0.5atr", (t.pierce_hi>0.5)&(t.close<t.hi72), -1),
 ("upthrust pierce>1atr", (t.pierce_hi>1.0)&(t.close<t.hi72), -1),
 ("upthrust pierce>1atr & vrel>3", (t.pierce_hi>1.0)&(t.close<t.hi72)&(t.vrel>3), -1),
])
print("## stink bids k*ATR from close, only when ranging & quiet (er48<0.15) vs trending (er48>0.35); returns from fill px on trade candles, ATR units")
rows=[]
for lab, cond in [("range er48<.15", t.er48<0.15), ("trend er48>.35", t.er48>0.35)]:
    for side in (1,-1):
        for k in (2.0,3.0):
            tt = t[cond]
            L = tt.close - side*k*tt.atr24
            if side==1:
                gap = tt.n_open<=L; fill = gap | (tt.n_low < L*(1-1e-4)); px = np.where(gap, tt.n_open, L)
            else:
                gap = tt.n_open>=L; fill = gap | (tt.n_high > L*(1+1e-4)); px = np.where(gap, tt.n_open, L)
            ev = tt[fill]; px = pd.Series(px, index=tt.index)[fill]; day = ev.time.dt.floor("D")
            r0 = side*(ev.n_close/px-1)/ev.atrp; r4 = side*(ev.o_4/px-1)/ev.atrp; r12 = side*(ev.o_12/px-1)/ev.atrp
            rows.append(dict(cond=lab, side=side, k=k, n=len(ev), days=day.nunique(), c0_N=r0.mean(), c0_t=cluster_t(r0,day), N4=r4.mean(), t4=cluster_t(r4,day), N12=r12.mean(), t12=cluster_t(r12,day),
                             y22=r4[ev.year==2022].mean(), y23=r4[ev.year==2023].mean(), y24=r4[ev.year==2024].mean(), bps4=(side*(ev.o_4/px-1)).mean()*1e4))
with pd.option_context("display.width", 350, "display.float_format", lambda v: f"{v:,.2f}"):
    print(pd.DataFrame(rows).to_string(index=False))
