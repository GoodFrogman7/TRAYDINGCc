"""Re-measure the main candidates in ATR units (the engine sizes by stop distance, so what pays is
forward return / ATR, not raw bps). fwdN_h = fwd_h / (ATR24_t / close_t)."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel.pkl"
p = pd.read_pickle(P).sort_values(["sym","time"]).reset_index(drop=True)
g = p.groupby("sym", sort=False)
p["liq_usd"] = p.liq_vol * p.close
p["liq_q99"] = g["liq_usd"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.99).shift(1))
p["ret6"] = g["close"].transform(lambda s: s / s.shift(6) - 1)
p["z6"] = p["ret6"] / (p["sig168"] * np.sqrt(6))
p["prem_z"] = g["premium"].transform(lambda s: (s - s.rolling(168, min_periods=100).mean().shift(1)) / s.rolling(168, min_periods=100).std().shift(1))
for h in (1,4,12,24):
    p[f"N{h}"] = p[f"fwd_{h}"] / p["atrp"]
    p[f"N{h}_d"] = p[f"fwd_{h}_d"] / p["atrp"]
p.to_pickle(P.replace("panel", "panel2"))
t = p[p.tradable & ~p.bar_missing].copy()
print("unconditional mean fwdN (ATR units):", t[["N1","N4","N12","N24"]].mean().round(4).to_dict())
def tab(rules):
    rows=[]
    for lab, m, sg in rules:
        ev = t[m]
        d = dict(rule=lab, n=len(ev), days=ev.time.dt.floor("D").nunique(), bps12=stats(ev,"fwd_12",sg).get("mean"))
        for h in (1,4,12,24):
            x = (ev[f"N{h}"]*sg).dropna()
            d[f"N{h}"] = x.mean(); d[f"t{h}"] = cluster_t(x, ev.loc[x.index,"time"].dt.floor("D"))
        d["N12_dly"] = (ev["N12_d"]*sg).mean()
        d["hit12"] = ((ev["fwd_12"]*sg)>0).mean()
        for y in (2022,2023,2024):
            d[f"{y}"] = (ev.loc[ev.year==y,"N12"]*sg).mean()
        d["maj"] = (ev.loc[ev.major,"N12"]*sg).mean(); d["alt"] = (ev.loc[~ev.major,"N12"]*sg).mean()
        rows.append(d)
    with pd.option_context("display.width", 320, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
tab([
 ("z1<-3 long", t.z1<-3, 1), ("z1<-4 long", t.z1<-4, 1), ("z1<-6 long", t.z1<-6, 1),
 ("z1>3 short", t.z1>3, -1), ("z1>4 short", t.z1>4, -1), ("z1>6 short", t.z1>6, -1),
 ("liq>q99 & z1<-3 long", (t.liq_usd>t.liq_q99)&(t.liq_q99>0)&(t.z1<-3), 1),
 ("liq>2q99 & z1<-3 long", (t.liq_usd>2*t.liq_q99)&(t.liq_q99>0)&(t.z1<-3), 1),
 ("z6<-3 long", t.z6<-3, 1), ("z6<-4 long", t.z6<-4, 1), ("z6<-5 long", t.z6<-5, 1),
 ("z6>3 short", t.z6>3, -1), ("z6>4 short", t.z6>4, -1),
 ("rsi<20 long", t.rsi14<20, 1), ("rsi<15 long", t.rsi14<15, 1), ("rsi>80 short", t.rsi14>80, -1), ("rsi>85 short", t.rsi14>85, -1),
 ("prem_z<-4 & ret1<0 long", (t.prem_z<-4)&(t.ret1<0), 1), ("premium<-0.3% long", t.premium<-0.003, 1),
 ("premium>0.3% short", t.premium>0.003, -1), ("premium>0.2% short", t.premium>0.002, -1),
 ("z48<-2.5 & er48<.15 long", (t.z48<-2.5)&(t.er48<0.15), 1), ("z48>2.5 & er48<.15 short", (t.z48>2.5)&(t.er48<0.15), -1),
 ("z24<-2.5 & er48<.15 long", (t.z24<-2.5)&(t.er48<0.15), 1), ("z24>2.5 & er48<.15 short", (t.z24>2.5)&(t.er48<0.15), -1),
])
