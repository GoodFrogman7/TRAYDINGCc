"""Does the panic-long family depend on the bigger trend? Split by coin above/below its 30-day mean BEFORE the drop
(sma720 of mark, compared with the mark 6 bars ago so the drop itself does not define the regime). MARK returns, ATR units."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel3.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
p["sma720"] = g["mark_close"].transform(lambda s: s.rolling(720, min_periods=720).mean())
p["pre"] = g["mark_close"].shift(6)
p["up"] = p.pre > g["sma720"].shift(6)
btc = p[p.sym=="PF_XBTUSD"].set_index("time")
p = p.join(btc["mz6"].rename("bz6"), on="time").join(btc["up"].rename("btc_up"), on="time")
p["ret720"] = p.pre / g["mark_close"].shift(726) - 1
t = p[p.tradable & ~p.bar_missing & p.mark_close.notna() & p.sma720.notna()].copy()
liq2 = (t.liq_usd>2*t.liq_q99)&(t.liq_q99>0)
def tab(rules, hy=12):
    rows=[]
    for lab, mm, sg in rules:
        ev = t[mm]; day = ev.time.dt.floor("D")
        d = dict(rule=lab, n=len(ev), days=day.nunique(), bps12=(ev.M12*sg).mean()*1e4, med12=(ev.M12*sg).median()*1e4)
        for h in (1,4,12,24):
            x = (ev[f"NM{h}"]*sg); d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, day)
        d["N12_dly"] = (ev["NM12_d"]*sg).mean(); d["hit"] = ((ev["M12"]*sg)>0).mean()
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,"NM12"]*sg).mean(); d[f"n{y}"] = int((ev.year==y).sum())
        rows.append(d)
    with pd.option_context("display.width", 380, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
tab([
 ("mz6<-4, coin was ABOVE 30d mean", (t.mz6<-4)&t.up, 1), ("mz6<-4, coin was BELOW 30d mean", (t.mz6<-4)&~t.up, 1),
 ("mz6<-3, ABOVE", (t.mz6<-3)&t.up, 1), ("mz6<-3, BELOW", (t.mz6<-3)&~t.up, 1),
 ("mz1<-3, ABOVE", (t.mz1<-3)&t.up, 1), ("mz1<-3, BELOW", (t.mz1<-3)&~t.up, 1),
 ("mz1<-4, ABOVE", (t.mz1<-4)&t.up, 1), ("mz1<-4, BELOW", (t.mz1<-4)&~t.up, 1),
 ("liq2 & mz1<-3, ABOVE", liq2&(t.mz1<-3)&t.up, 1), ("liq2 & mz1<-3, BELOW", liq2&(t.mz1<-3)&~t.up, 1),
 ("mz6<-4 & bz6<-3, ABOVE", (t.mz6<-4)&(t.bz6<-3)&t.up, 1), ("mz6<-4 & bz6<-3, BELOW", (t.mz6<-4)&(t.bz6<-3)&~t.up, 1),
 ("mz6<-4, BTC above its 30d mean", (t.mz6<-4)&(t.btc_up==True), 1), ("mz6<-4, BTC below", (t.mz6<-4)&(t.btc_up==False), 1),
 ("mz3<-4, ABOVE", (t.mz3<-4)&t.up, 1), ("mz3<-4, BELOW", (t.mz3<-4)&~t.up, 1),
])
