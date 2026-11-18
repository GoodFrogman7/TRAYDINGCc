import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
from desk.engine.core import Costs, Risk
rows = []
for cls in (S.BtcLiqFlush, S.HotVolBreakdownFade, S.LiquidityVacuumFade, S.AirPocketFade, S.WeekendDumpShort):
    st = cls()
    rows.append(E.check(st, label=st.name + " default"))
    rows.append(E.check(st, label=st.name + " fees x2", costs=Costs(fee_mult=2.0)))
    rows.append(E.check(st, label=st.name + " no guardian", risk=Risk(guardian=False)))
E.table(rows)
