import numpy as np, pandas as pd
from harness import *
from final import *
from desk.engine.core import Costs, Risk
s = Cascade()
rows=[]
p = {"z": 4.5}
base = run(s, p); rows.append(line(base, "cascade z4.5 zb3 stop4 hold12"))
rows.append(line(run(s, p, delay=1), "one bar late"))
rows.append(line(run(s, p, costs=Costs(fee_mult=2.0)), "fees x2"))
rows.append(line(run(s, p, risk=Risk(guardian=False)), "guardian off"))
show(rows)
t = trades_df(base)
se = t.r.std(ddof=1)/np.sqrt(len(t)); dR = t.groupby(t.entry_time.dt.floor("D")).r.sum()
print(f"avgR {t.r.mean():.3f} t {t.r.mean()/se:.2f}; clustered by day t {dR.mean()/(dR.std(ddof=1)/np.sqrt(len(dR))):.2f} days={len(dR)}; exits {base['summary']['exit_reasons']}")
print(t.groupby("year").agg(n=("r","size"), sumR=("r","sum"), win=("r", lambda x:(x>0).mean()), gross=("ret_bps","mean")).round(2).to_string())
# half-year stability of the premium fade
s = PremiumFade(); b = run(s, {}); t = trades_df(b)
t["half"] = t.entry_time.dt.year.astype(str) + "H" + ((t.entry_time.dt.month-1)//6+1).astype(str)
print("\npremium_fade by half-year:"); print(t.groupby("half").agg(n=("r","size"), sumR=("r","sum"), win=("r", lambda x:(x>0).mean()), net_bps=("net_bps","mean")).round(2).T.to_string())
print("per-symbol concentration (top 8 by trades):"); print(t.groupby("symbol").agg(n=("r","size"), sumR=("r","sum")).sort_values("n", ascending=False).head(8).round(2).T.to_string())
print("max simultaneous new entries in one bar:", t.groupby("entry_time").size().max(), "| share of trades entered with >=3 others same bar:", round((t.groupby("entry_time").r.transform("size")>=4).mean(),2))
print("summary:", {k: (round(v,4) if isinstance(v,float) else v) for k,v in b["summary"].items() if k in ("sharpe","sortino","worst_day","worst_month","best_month","pct_months_up","exposure","avg_gross_leverage","longest_losing_streak","funding_usd","fees_usd","gross_pnl_usd")})
