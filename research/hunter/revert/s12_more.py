"""More snapback hypotheses on MARK prices: (d) alt-vs-BTC residual, (f) OI wipe-out, (g) aggressor-sell exhaustion,
(h) premium collapse inside a panic bar."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel3.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
btc = p[p.sym=="PF_XBTUSD"].set_index("time")
for k in (1,4,6):
    p[f"mr{k}"] = np.log(p.mark_close) - np.log(g["mark_close"].shift(k))
    b = (np.log(btc.mark_close) - np.log(btc.mark_close.shift(k))).rename(f"b{k}")
    p = p.join(b, on="time")
p = p.join(btc["msig"].rename("bsig"), on="time")
g = p.groupby("sym", sort=False)
# trailing beta of alt vs BTC hourly mark returns (720h), lagged one bar
def beta(d):
    x, y = d["b1"], d["mr1"]
    cov = (x*y).rolling(720, min_periods=240).mean() - x.rolling(720, min_periods=240).mean()*y.rolling(720, min_periods=240).mean()
    var = x.rolling(720, min_periods=240).var()
    return (cov/var).shift(1)
p["beta"] = g.apply(beta).reset_index(level=0, drop=True)
for k in (1,4,6):
    p[f"res{k}"] = p[f"mr{k}"] - p.beta * p[f"b{k}"]
p["res1_sd"] = g["res1"].transform(lambda s: s.rolling(168, min_periods=168).std().shift(1))
for k in (1,4,6):
    p[f"rz{k}"] = p[f"res{k}"] / (p.res1_sd*np.sqrt(k))
    p[f"bz{k}"] = p[f"b{k}"] / (p.bsig*np.sqrt(k))
# OI change
for k in (1,3):
    p[f"doi{k}"] = p.oi / g["oi"].shift(k) - 1
p["doi1_q01"] = g["doi1"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.01).shift(1))
p["doi3_q01"] = g["doi3"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.01).shift(1))
# aggressor share
p["sell_share"] = p.sell_vol / (p.sell_vol + p.buy_vol).replace(0, np.nan)
p["dprem"] = p.premium - g["premium"].shift(1)
t = p[p.tradable & ~p.bar_missing & p.mark_close.notna()].copy()
alt = ~t.major
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
print("## (d) alt-specific residual vs BTC (alts only)")
tab([
 ("rz1<-4 long", alt&(t.rz1<-4), 1), ("rz1<-4 & BTC calm(|bz1|<1) long", alt&(t.rz1<-4)&(t.bz1.abs()<1), 1),
 ("rz4<-4 long", alt&(t.rz4<-4), 1), ("rz4<-4 & |bz4|<1 long", alt&(t.rz4<-4)&(t.bz4.abs()<1), 1),
 ("rz6<-4 long", alt&(t.rz6<-4), 1), ("rz6<-5 long", alt&(t.rz6<-5), 1),
 ("rz1>4 short", alt&(t.rz1>4), -1), ("rz4>4 short", alt&(t.rz4>4), -1), ("rz4>4 & |bz4|<1 short", alt&(t.rz4>4)&(t.bz4.abs()<1), -1),
 ("mz6<-4 & BTC z6<-3 (market-wide) long", (t.mz6<-4)&(t.bz6<-3), 1),
 ("mz6<-4 & BTC z6>-1.5 (idio) long", (t.mz6<-4)&(t.bz6>-1.5), 1),
])
print("## (f) open-interest wipe-out (oi from ~2023-03)")
tab([
 ("doi1<q01 & mz1<-2 long", (t.doi1<t.doi1_q01)&(t.mz1<-2), 1),
 ("doi1<q01 & mz1<-3 long", (t.doi1<t.doi1_q01)&(t.mz1<-3), 1),
 ("doi3<q01 & mz3<-3 long", (t.doi3<t.doi3_q01)&(t.mz3<-3), 1),
 ("doi1<-5% & mz1<-2 long", (t.doi1<-0.05)&(t.mz1<-2), 1),
 ("mz1<-3 & doi1>0 (no wipe) long", (t.mz1<-3)&(t.doi1>0), 1),
 ("doi1<q01 & mz1>2 short (short squeeze done)", (t.doi1<t.doi1_q01)&(t.mz1>2), -1),
])
print("## (g) aggressor-sell exhaustion")
tab([
 ("mz1<-3 & sell_share>.65 long", (t.mz1<-3)&(t.sell_share>0.65), 1),
 ("mz1<-3 & sell_share<.5 long", (t.mz1<-3)&(t.sell_share<0.5), 1),
])
print("## (h) premium collapses during a down bar (perp sold harder than spot)")
tab([
 ("dprem<-0.15% & mz1<-2 long", (t.dprem<-0.0015)&(t.mz1<-2), 1),
 ("dprem<-0.25% & mz1<-2 long", (t.dprem<-0.0025)&(t.mz1<-2), 1),
 ("dprem>0.15% & mz1>2 short", (t.dprem>0.0015)&(t.mz1>2), -1),
 ("dprem>0.25% & mz1>2 short", (t.dprem>0.0025)&(t.mz1>2), -1),
 ("dprem>0.15% short any", (t.dprem>0.0015), -1), ("dprem<-0.15% long any", (t.dprem<-0.0015), 1),
])
