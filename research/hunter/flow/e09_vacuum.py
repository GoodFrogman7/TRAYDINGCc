"""Liquidity-vacuum fade with a fixed-% disaster stop: neighbours and cost stress (slip x3 because the signal fires when spread is >=3x normal)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
from desk.engine.core import Costs, Risk
V = dict(sp_mult=3.0, drop_atr=2.0, stop_atr=-0.08)
rows = []
for nm, p, mh, kw in (
    ("sp3 drop2 stop8% hold24", V, 24, {}),
    ("sp2.5", {**V, "sp_mult": 2.5}, 24, {}),
    ("sp4", {**V, "sp_mult": 4.0}, 24, {}),
    ("drop1.5", {**V, "drop_atr": 1.5}, 24, {}),
    ("drop2.5", {**V, "drop_atr": 2.5}, 24, {}),
    ("stop10%", {**V, "stop_atr": -0.10}, 24, {}),
    ("hold12", V, 12, {}),
    ("hold36", V, 36, {}),
    ("fees x2", V, 24, dict(costs=Costs(fee_mult=2.0))),
    ("slip x3", V, 24, dict(costs=Costs(slip_mult=3.0))),
    ("no guardian", V, 24, dict(risk=Risk(guardian=False))),
):
    st = S.LiquidityVacuumFade(); rows.append(E.check(st, p, label=nm, max_hold=mh, **kw))
E.table(rows)
r = rows[0]; t = r["tdf"]; t["d"] = t.entry_time.astype(str).str[:10]
byd = t.groupby("d").pnl.sum() / 100
print(f"entry days {len(byd)}, winning days {(byd>0).mean():.2f}, total {byd.sum():.1f}%, without best 5 days {byd.sum()-byd.nlargest(5).sum():.1f}%, best5 {byd.nlargest(5).round(2).to_dict()}")
print("majors vs alts pnl %:", round(t[t.symbol.isin(['PF_XBTUSD','PF_ETHUSD'])].pnl.sum()/100, 2), "/", round(t[~t.symbol.isin(['PF_XBTUSD','PF_ETHUSD'])].pnl.sum()/100, 2),
      " n majors", int(t.symbol.isin(['PF_XBTUSD','PF_ETHUSD']).sum()))
print(t.groupby(t.entry_time.astype(str).str[:7]).pnl.sum().div(100).round(2).to_dict())
