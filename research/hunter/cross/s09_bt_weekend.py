from research.hunter.cross.bt import *
from research.hunter.cross.strats import *
from desk.engine.core import Costs

rows = []
S = WeekendFollow()
for lab, p in [("default all thr0.5% stop4", {}), ("thr 0", {"thr": 0.0}), ("thr 1%", {"thr": 0.01}), ("stop 3", {"stop_atr": 3.0}), ("stop 5", {"stop_atr": 5.0}),
               ("btc only", {"who": "btc"}), ("btc+eth", {"who": "majors"}), ("alts only", {"who": "alts"}), ("agree only", {"agree": True}),
               ("sig 19:00", {"sig_hour": 19}), ("sig 23:00", {"sig_hour": 23}), ("look 24", {"look": 24}), ("look 60", {"look": 60})]:
    rows.append(report(S, p, lab)["row"])
rows.append(report(Delayed(S), {}, "default, 1 bar late")["row"])
rows.append(report(S, {}, "default, fees x2", costs=Costs(fee_mult=2.0))["row"])
rows.append(report(S, {}, "default, slip x3", costs=Costs(slip_mult=3.0))["row"])
table(rows)
r = report(S, {})
tr = r["tr"]
print("\nper-weekend PnL (% equity): n weekends", tr.groupby("entry_time").pnl.sum().shape[0], " share positive", round((tr.groupby("entry_time").pnl.sum() > 0).mean(), 3))
wk = tr.groupby("entry_time").pnl.sum() / 100
print("worst weekends:", wk.sort_values().head(5).round(2).to_dict())
print("best weekends:", wk.sort_values().tail(5).round(2).to_dict())
print("by symbol:", (tr.groupby("symbol").pnl.agg(["count", "sum"]).sort_values("sum").round(0)).T.to_string())
