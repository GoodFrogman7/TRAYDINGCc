"""Which trade structure lets the snapback survive the engine (stops, costs, Guardian)? A handful of
hypothesis-driven structures per signal family, NOT a parameter sweep."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
from desk.engine.core import Costs, Risk
rows = []
structs = {
    "A mkt stop4 hold12": dict(p=dict(stop_atr=4.0), vb=1, mh=12),
    "B mkt stop6 hold12": dict(p=dict(stop_atr=6.0), vb=1, mh=12),
    "C lim-1 stop3 hold12": dict(p=dict(stop_atr=3.0, limit_atr=1.0), vb=3, mh=12),
    "D lim-1 stop3 tp2 hold12": dict(p=dict(stop_atr=3.0, limit_atr=1.0, tp_atr=2.0), vb=3, mh=12),
    "E mkt stop4 tp2 hold12": dict(p=dict(stop_atr=4.0, tp_atr=2.0), vb=1, mh=12),
}
for cls in (S.BtcLiqFlush, S.HotVolBreakdownFade, S.LiquidityVacuumFade, S.AirPocketFade):
    for nm, cfg in structs.items():
        st = cls(); st.valid_bars = cfg["vb"]
        rows.append(E.check(st, cfg["p"], label=f"{st.name[5:]} | {nm}", max_hold=cfg["mh"]))
    E.table(rows[-len(structs):]); print()
