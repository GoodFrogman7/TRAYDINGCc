from research.hunter.cross.bt import *
from research.hunter.cross.strats import *
from desk.engine.core import Costs

rows = []
S = WeekendFollow()
base = {"who": "majors"}
for lab, p in [("BTC+ETH thr0.5% stop4", {}), ("thr 0", {"thr": 0.0}), ("thr 1%", {"thr": 0.01}), ("stop 3", {"stop_atr": 3.0}), ("stop 5", {"stop_atr": 5.0}),
               ("stop 6", {"stop_atr": 6.0}), ("thr0 stop3", {"thr": 0.0, "stop_atr": 3.0}), ("thr0 stop5", {"thr": 0.0, "stop_atr": 5.0}),
               ("thr1% stop3", {"thr": 0.01, "stop_atr": 3.0}), ("thr1% stop5", {"thr": 0.01, "stop_atr": 5.0}),
               ("look 24", {"look": 24}), ("look 36", {"look": 36}), ("look 60", {"look": 60}), ("look 72", {"look": 72}),
               ("sig 19:00", {"sig_hour": 19}), ("sig 20:00", {"sig_hour": 20}), ("sig 22:00", {"sig_hour": 22}), ("sig 23:00", {"sig_hour": 23}),
               ("agree", {"agree": True})]:
    rows.append(report(S, {**base, **p}, lab)["row"])
rows.append(report(Delayed(S), base, "default, 1 bar late")["row"])
rows.append(report(S, base, "default, fees x2", costs=Costs(fee_mult=2.0))["row"])
rows.append(report(S, base, "default, slip x3", costs=Costs(slip_mult=3.0))["row"])
class WF12(WeekendFollow):
    max_hold = 12
class WF36(WeekendFollow):
    max_hold = 36
rows.append(report(WF12(), base, "hold 12")["row"]); rows.append(report(WF36(), base, "hold 36")["row"])
table(rows)
r = report(S, base)
print("monthly worst/best:", r["summary"]["worst_month"], r["summary"]["best_month"], "pct months up", r["summary"]["pct_months_up"])
tr = r["tr"]; tr["half"] = pd.to_datetime(tr.entry_time).dt.to_period("Q")
print(tr.groupby("half").pnl.agg(["count", "sum"]).round(0).T.to_string())
