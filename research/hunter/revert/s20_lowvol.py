"""H6 again at multi-bar horizons on MARK prices: drifts on thin volume (k-bar move, k-bar volume vs trailing median)."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel3.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
for k in (12, 24):
    p[f"mzk{k}"] = (np.log(p.mark_close) - np.log(g["mark_close"].shift(k))) / (p.msig*np.sqrt(k))
    vs = g["usd"].transform(lambda s: s.rolling(k, min_periods=k).sum())
    p[f"vs{k}"] = vs
    p[f"vr{k}"] = vs / g[f"vs{k}"].transform(lambda s: s.rolling(720, min_periods=240).median().shift(1))
t = p[p.tradable & ~p.bar_missing & p.mark_close.notna()].copy()
def tab(rules, hy=12):
    rows=[]
    for lab, mm, sg in rules:
        ev = t[mm]; day = ev.time.dt.floor("D")
        d = dict(rule=lab, n=len(ev), days=day.nunique(), bps12=(ev.M12*sg).mean()*1e4, bps24=(ev.M24*sg).mean()*1e4)
        for h in (4,12,24,48):
            x = (ev[f"M{h}"]*sg/ev.atrp); d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, day)
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,"NM24"]*sg).mean()
        rows.append(d)
    with pd.option_context("display.width", 350, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
r=[]
for k in (12,24):
    z, v = t[f"mzk{k}"], t[f"vr{k}"]
    r += [(f"k{k}: z>2 & vol<0.7 short", (z>2)&(v<0.7), -1), (f"k{k}: z>2 & vol>1.5 short", (z>2)&(v>1.5), -1),
          (f"k{k}: z<-2 & vol<0.7 long", (z<-2)&(v<0.7), 1), (f"k{k}: z<-2 & vol>1.5 long", (z<-2)&(v>1.5), 1),
          (f"k{k}: z>1.5 & vol<0.6 short", (z>1.5)&(v<0.6), -1), (f"k{k}: z<-1.5 & vol<0.6 long", (z<-1.5)&(v<0.6), 1)]
tab(r)
