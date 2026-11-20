"""Resting bid k*ATR below the last close, re-quoted every bar, conditional on the trailing 48h regime.
Fill model = engine. Returns from the fill price on trade candles, ATR units (ATR24 at the quote bar)."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel3.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
for c in ("open","high","low","close"):
    p[f"n_{c}"] = g[c].shift(-1)
for h in (1,4,12,24):
    p[f"o_{h}"] = g["open"].shift(-(1+h))
p["ret48"] = p.close / g["close"].shift(48) - 1
p["lo_after12"] = g["low"].transform(lambda s: s.shift(-2)[::-1].rolling(12, min_periods=1).min()[::-1])
t = p[p.tradable & ~p.bar_missing & p.atr24.notna() & ((p.close/p.mark_close-1).abs()<=0.003)].copy()
rows=[]
def study(lab, cond, k, side=1):
    tt = t[cond]
    L = tt.close - side*k*tt.atr24
    if side==1:
        gap = tt.n_open<=L; fill = gap | (tt.n_low < L*(1-1e-4)); px = np.where(gap, tt.n_open, L)
    else:
        gap = tt.n_open>=L; fill = gap | (tt.n_high > L*(1+1e-4)); px = np.where(gap, tt.n_open, L)
    ev = tt[fill]; px = pd.Series(px, index=tt.index)[fill]; day = ev.time.dt.floor("D")
    d = dict(rule=lab, k=k, quotes=len(tt), n=len(ev), days=day.nunique())
    for nm, col in (("c0","n_close"),("o4","o_4"),("o12","o_12"),("o24","o_24")):
        r = side*(ev[col]/px-1); rn = r/ev.atrp
        d[f"{nm}_N"] = rn.mean(); d[f"{nm}_t"] = cluster_t(rn, day)
        if nm=="o12": d["bps12"]=r.mean()*1e4; d["med12"]=r.median()*1e4; d["hit12"]=(r>0).mean()
    r12 = side*(ev["o_12"]/px-1)/ev.atrp
    for y in (2022,2023,2024): d[f"{y}"] = r12[ev.year==y].mean()
    d["maj"] = r12[ev.major].mean(); d["n_maj"]=int(ev.major.sum())
    if side==1:
        d["fillbar_low_N"] = ((ev.n_low/px-1)/ev.atrp).quantile(.1)   # how far through the bid the fill bar went (10th pct)
        d["mae12_p10"] = ((np.minimum(ev.n_low, ev.lo_after12)/px-1)/ev.atrp).quantile(.1)
    rows.append(d)
for k in (2.0,3.0,4.0):
    study("any regime", t.close>0, k)
    study("er48>.35", t.er48>0.35, k)
    study("er48>.35 & ret48<0 (downtrend)", (t.er48>0.35)&(t.ret48<0), k)
    study("er48>.35 & ret48>0 (uptrend)", (t.er48>0.35)&(t.ret48>0), k)
    study("er48>.25", t.er48>0.25, k)
    study("er48<.25", t.er48<0.25, k)
    study("ret48<-2*sig*sqrt48 (48h selloff)", (t.ret48 < -1.5*t.sig168*np.sqrt(48)), k)
with pd.option_context("display.width", 380, "display.float_format", lambda v: f"{v:,.2f}"):
    print(pd.DataFrame(rows).to_string(index=False))
