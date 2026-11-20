"""H7: liquidation flush. liq_vol spike + down bar -> long; mirror for short squeezes."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel.pkl"
p = pd.read_pickle(P)
p = p.sort_values(["sym","time"]).reset_index(drop=True)
g = p.groupby("sym", sort=False)
p["liq_usd"] = p.liq_vol * p.close
p["liq_share"] = p.liq_vol / p.volume.replace(0, np.nan)
# trailing reference: 30d rolling 99th pct of liq_usd, lagged
p["liq_q99"] = g["liq_usd"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.99).shift(1))
p["liq_q95"] = g["liq_usd"].transform(lambda s: s.rolling(720, min_periods=240).quantile(0.95).shift(1))
p["liq_sum720"] = g["liq_usd"].transform(lambda s: s.rolling(720, min_periods=240).sum().shift(1))
t = p[p.tradable & ~p.bar_missing].copy()
print("liq_vol coverage by year (share of tradable bars with liq_vol>0, notna):")
print(t.groupby("year").agg(notna=("liq_vol", lambda s: s.notna().mean()), pos=("liq_vol", lambda s: (s>0).mean()), share_med=("liq_share", lambda s: s[s>0].median())))
print(t.groupby("sym").agg(pos=("liq_vol", lambda s: (s>0).mean()), q99=("liq_usd", lambda s: s.quantile(.99))).round(3).T.to_string())

rows=[]
for lab, m, sg in [
  ("liq>q99 & down bar (ret1<0)", (t.liq_usd>t.liq_q99)&(t.liq_q99>0)&(t.ret1<0), 1),
  ("liq>q99 & ret1<-1.5%",        (t.liq_usd>t.liq_q99)&(t.liq_q99>0)&(t.ret1<-0.015), 1),
  ("liq>q99 & z1<-3",             (t.liq_usd>t.liq_q99)&(t.liq_q99>0)&(t.z1<-3), 1),
  ("liq>2*q99 & z1<-3",           (t.liq_usd>2*t.liq_q99)&(t.liq_q99>0)&(t.z1<-3), 1),
  ("liq_share>10% & z1<-3",       (t.liq_share>0.10)&(t.z1<-3), 1),
  ("z1<-3, liq<=q95 (no liq)",    (t.liq_usd<=t.liq_q95)&(t.z1<-3), 1),
  ("liq>q99 & up bar (short)",    (t.liq_usd>t.liq_q99)&(t.liq_q99>0)&(t.ret1>0), -1),
  ("liq>q99 & z1>3 (short)",      (t.liq_usd>t.liq_q99)&(t.liq_q99>0)&(t.z1>3), -1),
  ("z1>3, liq<=q95 (short)",      (t.liq_usd<=t.liq_q95)&(t.z1>3), -1),
]:
    ev = t[m]
    d = dict(rule=lab, n=len(ev), days=ev.time.dt.floor("D").nunique())
    for h in (1,4,12,24):
        s = stats(ev, f"fwd_{h}", sg); d[f"m{h}"]=s.get("mean"); d[f"t{h}"]=s.get("t_cl")
    s = stats(ev, "fwd_12_d", sg); d["m12_delay"]=s.get("mean")
    for y in (2022,2023,2024):
        d[f"m12_{y}"] = stats(ev[ev.year==y], "fwd_12", sg).get("mean")
    d["m12_maj"] = stats(ev[ev.major], "fwd_12", sg).get("mean")
    rows.append(d)
with pd.option_context("display.width", 300, "display.float_format", lambda v: f"{v:,.1f}"):
    print(pd.DataFrame(rows).to_string(index=False))
