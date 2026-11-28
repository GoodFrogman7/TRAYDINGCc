"""Aggregate (market-wide) premium vs coin-specific premium. MARK forward returns, ATR units."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel3.pkl"
p = pd.read_pickle(P)
tr = p[p.tradable & ~p.bar_missing]
agg = tr.groupby("time")["premium"].median().rename("prem_mkt")
p = p.join(agg, on="time")
p["prem_rel"] = p.premium - p.prem_mkt
t = p[p.tradable & ~p.bar_missing & p.mark_close.notna()].copy()
print(t[["prem_mkt","prem_rel"]].describe(percentiles=[.01,.05,.5,.95,.99]).T.round(5).to_string())
def tab(rules, hy=4):
    rows=[]
    for lab, mm, sg in rules:
        ev = t[mm]; day = ev.time.dt.floor("D")
        d = dict(rule=lab, n=len(ev), days=day.nunique(), bps4=(ev.M4*sg).mean()*1e4, bps12=(ev.M12*sg).mean()*1e4)
        for h in (1,4,12,24):
            x = (ev[f"NM{h}"]*sg); d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, day)
        d[f"N{hy}_dly"] = (ev[f"NM{hy}_d"]*sg).mean(); d["hit"] = ((ev[f"M{hy}"]*sg)>0).mean()
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,f"NM{hy}"]*sg).mean()
        d["maj"] = (ev.loc[ev.major,f"NM{hy}"]*sg).mean()
        rows.append(d)
    with pd.option_context("display.width", 350, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
tab([
 ("mkt prem>0.15% short all", t.prem_mkt>0.0015, -1), ("mkt prem>0.2% short all", t.prem_mkt>0.002, -1),
 ("mkt prem>0.15% short majors", (t.prem_mkt>0.0015)&t.major, -1),
 ("mkt prem<-0.1% long all", t.prem_mkt<-0.001, 1), ("mkt prem<-0.15% long all", t.prem_mkt<-0.0015, 1),
 ("coin prem>0.3% & mkt<0.1% (coin-specific) short", (t.premium>0.003)&(t.prem_mkt<0.001), -1),
 ("coin prem>0.3% & mkt>0.1% (market-wide) short", (t.premium>0.003)&(t.prem_mkt>=0.001), -1),
 ("coin prem<-0.3% & mkt>-0.1% (coin-specific) long", (t.premium<-0.003)&(t.prem_mkt>-0.001), 1),
 ("coin prem<-0.3% & mkt<-0.1% (market-wide) long", (t.premium<-0.003)&(t.prem_mkt<=-0.001), 1),
 ("prem_rel>0.3% short", t.prem_rel>0.003, -1), ("prem_rel<-0.3% long", t.prem_rel<-0.003, 1),
 ("prem>0.3% & mz1>2 (rich after pump) short", (t.premium>0.003)&(t.mz1>2), -1),
 ("prem>0.3% & |mz1|<1 (rich, calm) short", (t.premium>0.003)&(t.mz1.abs()<1), -1),
 ("prem<-0.3% & mz1<-2 long", (t.premium<-0.003)&(t.mz1<-2), 1),
 ("prem<-0.3% & |mz1|<1 long", (t.premium<-0.003)&(t.mz1.abs()<1), 1),
])
