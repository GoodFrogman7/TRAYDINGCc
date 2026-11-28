"""H8 deeper: perp-vs-index dislocation. premium = hour-average (mark-index)/index; basis_c = close/spot_close-1."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel2.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
p["basis_c"] = p.close / p.spot_close - 1
p["basis_m"] = p.mark_close / p.spot_close - 1
p["prem_med"] = g["premium"].transform(lambda s: s.rolling(168, min_periods=100).median().shift(1))
p["prem_x"] = p.premium - p.prem_med
p["prem_q99"] = g["premium"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.99).shift(1))
p["prem_q01"] = g["premium"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.01).shift(1))
p["dprem"] = p.premium - g["premium"].shift(1)
t = p[p.tradable & ~p.bar_missing].copy()
print(t[["premium","basis_c","basis_m","funding"]].describe(percentiles=[.001,.01,.05,.5,.95,.99,.999]).T.to_string())
print("share of bars premium>0.3% by year:", t.groupby("year").apply(lambda d: (d.premium>0.003).mean()).round(4).to_dict())
print("share of bars premium<-0.3% by year:", t.groupby("year").apply(lambda d: (d.premium<-0.003).mean()).round(4).to_dict())
print("premium>0.3% by symbol count:", t[t.premium>0.003].groupby("sym").size().sort_values(ascending=False).head(12).to_dict())
print("premium<-0.3% by symbol count:", t[t.premium<-0.003].groupby("sym").size().sort_values(ascending=False).head(12).to_dict())
print("mean hourly funding (bps) when premium>0.3%:", t.loc[t.premium>0.003,"funding"].mean()*1e4, " when <-0.3%:", t.loc[t.premium<-0.003,"funding"].mean()*1e4)
def tab(rules):
    rows=[]
    for lab, m, sg in rules:
        ev = t[m]
        d = dict(rule=lab, n=len(ev), days=ev.time.dt.floor("D").nunique(), syms=ev.sym.nunique(), bps4=stats(ev,"fwd_4",sg).get("mean"), bps12=stats(ev,"fwd_12",sg).get("mean"))
        for h in (1,4,12,24):
            x = (ev[f"N{h}"]*sg).dropna()
            d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, ev.loc[x.index,"time"].dt.floor("D"))
        d["N4_dly"] = (ev["N4_d"]*sg).mean()
        d["hit4"] = ((ev["fwd_4"]*sg)>0).mean()
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,"N4"]*sg).mean()
        d["maj"] = (ev.loc[ev.major,"N4"]*sg).mean(); d["alt"] = (ev.loc[~ev.major,"N4"]*sg).mean()
        rows.append(d)
    with pd.option_context("display.width", 350, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
tab([
 ("premium>0.2% short", t.premium>0.002, -1), ("premium>0.3% short", t.premium>0.003, -1), ("premium>0.5% short", t.premium>0.005, -1),
 ("prem>q99 & >0.15% short", (t.premium>t.prem_q99)&(t.premium>0.0015), -1),
 ("prem>q99 short", (t.premium>t.prem_q99), -1),
 ("prem_x>0.25% short", t.prem_x>0.0025, -1),
 ("basis_c>0.4% short", t.basis_c>0.004, -1), ("basis_c>0.6% short", t.basis_c>0.006, -1),
 ("basis_m>0.3% short", t.basis_m>0.003, -1),
 ("premium<-0.2% long", t.premium<-0.002, 1), ("premium<-0.3% long", t.premium<-0.003, 1), ("premium<-0.5% long", t.premium<-0.005, 1),
 ("prem<q01 & <-0.15% long", (t.premium<t.prem_q01)&(t.premium<-0.0015), 1),
 ("prem<q01 long", (t.premium<t.prem_q01), 1),
 ("prem_x<-0.25% long", t.prem_x<-0.0025, 1),
 ("basis_c<-0.4% long", t.basis_c<-0.004, 1), ("basis_c<-0.6% long", t.basis_c<-0.006, 1), ("basis_c<-1% long", t.basis_c<-0.01, 1),
 ("basis_m<-0.3% long", t.basis_m<-0.003, 1),
 ("basis_c<-0.4% & z1<-2 long", (t.basis_c<-0.004)&(t.z1<-2), 1),
 ("z1<-3 & basis_c<-0.3% long", (t.z1<-3)&(t.basis_c<-0.003), 1),
 ("z1<-3 & basis_c>-0.1% long", (t.z1<-3)&(t.basis_c>-0.001), 1),
 ("z1>3 & basis_c>0.3% short", (t.z1>3)&(t.basis_c>0.003), -1),
 ("z1>3 & basis_c<0.1% short", (t.z1>3)&(t.basis_c<0.001), -1),
])
