"""Hypothesis: ATR-multiple stops shrink the position exactly when the snapback is largest (violent events).
A fixed-percentage disaster stop keeps notional constant. One check per fade family, 8% and 6%."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
from desk.engine.core import Costs, Risk
rows = []
for cls, p, mh in ((S.LiquidityVacuumFade, dict(sp_mult=3.0), 24), (S.LiquidityVacuumFade, dict(sp_mult=2.0), 24),
                   (S.BtcLiqFlush, dict(), 12), (S.AirPocketFade, dict(), 12), (S.HotVolBreakdownFade, dict(rank_min=0.7), 12),
                   (S.StressBid, dict(), 24)):
    for sp in (-0.08, -0.06):
        st = cls(); rows.append(E.check(st, {**p, "stop_atr": sp}, label=f"{st.name[5:]} {p} stop {int(-sp*100)}% hold{mh}", max_hold=mh))
E.table(rows)
