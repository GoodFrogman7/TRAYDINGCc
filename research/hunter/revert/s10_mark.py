"""Re-test the surviving candidates on MARK prices (order-book based, not the last print).
Kraken's hourly candle OPEN equals the previous CLOSE in 100% of bars, so 'next open' is the last trade,
which on thin alts can be stale / an off-book print. Honest forward return here:
    fwdM_h = mark_close[t+h] / mark_close[t] - 1     (enter at the mark at the signal close)
    fwdM_h_d = mark_close[t+1+h] / mark_close[t+1] - 1  (one bar late)
Signals use mark returns too. NM = fwdM / (ATR24/close)."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel2.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
m = p["mark_close"]
p["mret1"] = np.log(m) - np.log(g["mark_close"].shift(1))
p["msig"] = g["mret1"].transform(lambda s: s.rolling(168, min_periods=168).std().shift(1))
p["mz1"] = p.mret1 / p.msig
p["mz6"] = (np.log(m) - np.log(g["mark_close"].shift(6))) / (p.msig * np.sqrt(6))
p["mz3"] = (np.log(m) - np.log(g["mark_close"].shift(3))) / (p.msig * np.sqrt(3))
p["mz12"] = (np.log(m) - np.log(g["mark_close"].shift(12))) / (p.msig * np.sqrt(12))
for h in (1,2,4,8,12,24,48):
    p[f"M{h}"] = (g["mark_close"].shift(-h) / m - 1)
    p[f"M{h}_d"] = (g["mark_close"].shift(-h-1) / g["mark_close"].shift(-1) - 1)
    p[f"NM{h}"] = p[f"M{h}"] / p.atrp
    p[f"NM{h}_d"] = p[f"M{h}_d"] / p.atrp
p["c_vs_mark"] = p.close / p.mark_close - 1
p.to_pickle(P.replace("panel2", "panel3"))
t = p[p.tradable & ~p.bar_missing & p.mark_close.notna()].copy()
print("unconditional NM:", t[["NM1","NM4","NM12","NM24"]].mean().round(4).to_dict())
def tab(rules, hy=12):
    rows=[]
    for lab, mm, sg in rules:
        ev = t[mm]; day = ev.time.dt.floor("D")
        d = dict(rule=lab, n=len(ev), days=day.nunique(), bps4=(ev.M4*sg).mean()*1e4, bps12=(ev.M12*sg).mean()*1e4, med12=(ev.M12*sg).median()*1e4)
        for h in (1,4,12,24):
            x = (ev[f"NM{h}"]*sg); d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, day)
        d[f"N{hy}_dly"] = (ev[f"NM{hy}_d"]*sg).mean(); d["hit"] = ((ev[f"M{hy}"]*sg)>0).mean()
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,f"NM{hy}"]*sg).mean()
        d["maj"] = (ev.loc[ev.major,f"NM{hy}"]*sg).mean(); d["alt"] = (ev.loc[~ev.major,f"NM{hy}"]*sg).mean()
        rows.append(d)
    with pd.option_context("display.width", 350, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
liq99 = (t.liq_usd>t.liq_q99)&(t.liq_q99>0); liq2 = (t.liq_usd>2*t.liq_q99)&(t.liq_q99>0)
print("\n## panic / capitulation longs (mark based)")
tab([
 ("mz1<-3 long", t.mz1<-3, 1), ("mz1<-4 long", t.mz1<-4, 1), ("mz1<-6 long", t.mz1<-6, 1),
 ("liq>q99 & mz1<-3 long", liq99&(t.mz1<-3), 1), ("liq>2q99 & mz1<-3 long", liq2&(t.mz1<-3), 1), ("liq>2q99 & mz1<-2 long", liq2&(t.mz1<-2), 1),
 ("no-liq & mz1<-3 long", (~liq99)&(t.mz1<-3), 1),
 ("mz6<-3 long", t.mz6<-3, 1), ("mz6<-4 long", t.mz6<-4, 1), ("mz6<-5 long", t.mz6<-5, 1),
 ("mz3<-4 long", t.mz3<-4, 1), ("mz12<-4 long", t.mz12<-4, 1),
 ("premium<-0.3% long", t.premium<-0.003, 1), ("premium<-0.2% long", t.premium<-0.002, 1),
])
print("\n## euphoria / squeeze shorts (mark based)")
tab([
 ("mz1>3 short", t.mz1>3, -1), ("mz1>4 short", t.mz1>4, -1), ("liq>q99 & mz1>3 short", liq99&(t.mz1>3), -1),
 ("mz6>4 short", t.mz6>4, -1), ("mz6>5 short", t.mz6>5, -1),
 ("premium>0.3% short", t.premium>0.003, -1), ("premium>0.2% short", t.premium>0.002, -1), ("premium>0.4% short", t.premium>0.004, -1),
])
