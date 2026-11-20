"""Why does the engine show ~45 bps gross per cascade trade when the event study says ~170 bps at 12h? Reconcile."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import strats as S, engine_check as E, features as F, lib
from desk.engine.core import Costs, Risk
pd.set_option("display.width", 250)

st = S.BtcLiqFlush(); st.valid_bars = 1
res = E.check(st, dict(stop_atr=6.0), max_hold=12, risk=Risk(guardian=False))
t = res["tdf"].copy()
t["entry_time"] = pd.to_datetime(t["entry_time"])
print(res["row"])
print(t.reason.value_counts().to_dict())
# event-study events
P = F.panel()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz})
X = F.stack(P).join(bs, on="time")
X = X[X.tradable & ~X.miss]
Ev = X[(X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3)].copy()
Ev["entry_time"] = Ev["time"] + pd.Timedelta(hours=1)
m = Ev.merge(t, left_on=["sym", "entry_time"], right_on=["symbol", "entry_time"], how="outer", indicator=True)
print(m["_merge"].value_counts().to_dict())
both = m[m._merge == "both"]
print("matched: event f12 mean bps", round(both.f12.mean() * 1e4, 1), "engine gross bps", round(both.gross_bps.mean(), 1), "n", len(both))
lo = m[m._merge == "left_only"]
print("events with NO trade (already in position / blocked): n", len(lo), "f12 mean", round(lo.f12.mean() * 1e4, 1), "f4", round(lo.f4.mean() * 1e4, 1))
ro = m[m._merge == "right_only"]
print("trades with no event-study row:", len(ro), "gross", round(ro.gross_bps.mean(), 1) if len(ro) else None)
print("\nmatched trades by exit reason:")
print(both.groupby("reason").agg(n=("f12", "size"), f12=("f12", lambda s: round(s.mean() * 1e4, 1)), gross=("gross_bps", "mean"), net=("net_bps", "mean"), R=("r", "mean")).round(2))
print("\nfirst signal per symbol per cascade vs later signals (event study):")
Ev = Ev.sort_values(["sym", "time"])
Ev["gap"] = Ev.groupby("sym")["time"].diff().dt.total_seconds() / 3600
Ev["first"] = Ev.gap.isna() | (Ev.gap > 12)
print(Ev.groupby("first").agg(n=("f12", "size"), f4=("f4", lambda s: round(s.mean() * 1e4, 1)), f12=("f12", lambda s: round(s.mean() * 1e4, 1)), f24=("f24", lambda s: round(s.mean() * 1e4, 1))))
print(Ev[Ev["first"]].groupby("year").agg(n=("f12", "size"), f4=("f4", lambda s: round(s.mean() * 1e4, 1)), f12=("f12", lambda s: round(s.mean() * 1e4, 1)), f24=("f24", lambda s: round(s.mean() * 1e4, 1))))
