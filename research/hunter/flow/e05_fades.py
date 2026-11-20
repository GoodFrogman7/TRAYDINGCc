"""Design-window engine check of the long-fade family with the structures the path study suggests."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
from desk.engine.core import Costs, Risk

def block(title, cls, variants, extra=True):
    rows = []
    for nm, (p, mh, vb) in variants.items():
        st = cls(); st.valid_bars = vb
        rows.append(E.check(st, p, label=nm, max_hold=mh))
    if extra:
        nm0, (p0, mh0, vb0) = next(iter(variants.items()))
        for lab, kw in (("fees x2", dict(costs=Costs(fee_mult=2.0))), ("slip x2", dict(costs=Costs(slip_mult=2.0))), ("no guardian", dict(risk=Risk(guardian=False)))):
            st = cls(); st.valid_bars = vb0
            rows.append(E.check(st, p0, label=nm0 + " | " + lab, max_hold=mh0, **kw))
    print(f"\n##### {title}")
    E.table(rows)

class FlushAlts(S.BtcLiqFlush):
    def intents(self, data, p):
        out = super().intents(data, p)
        for s in ("PF_XBTUSD", "PF_ETHUSD"):
            if s in out: out[s]["side"] = 0
        return out

block("BTC liq flush", S.BtcLiqFlush, {
    "mkt stop4 hold6": (dict(stop_atr=4.0), 6, 1),
    "mkt stop3 hold4": (dict(stop_atr=3.0), 4, 1),
    "mkt stop4 hold12": (dict(stop_atr=4.0), 12, 1),
    "mkt stop6 hold6": (dict(stop_atr=6.0), 6, 1),
    "mkt stop4 hold6 z2.5": (dict(stop_atr=4.0, z=2.5), 6, 1),
    "mkt stop4 hold6 z3.5": (dict(stop_atr=4.0, z=3.5), 6, 1),
})
block("BTC liq flush, alts only", FlushAlts, {
    "alts mkt stop4 hold6": (dict(stop_atr=4.0), 6, 1),
    "alts mkt stop4 hold12": (dict(stop_atr=4.0), 12, 1),
}, extra=False)
block("air pocket", S.AirPocketFade, {
    "mkt stop2.5 hold24": (dict(stop_atr=2.5), 24, 1),
    "mkt stop4 hold24": (dict(stop_atr=4.0), 24, 1),
    "mkt stop2.5 hold24 vmax2.5": (dict(stop_atr=2.5, vmax=2.5), 24, 1),
    "mkt stop2.5 hold24 vmax6": (dict(stop_atr=2.5, vmax=6.0), 24, 1),
})
block("hot breakdown, limit entry", S.HotVolBreakdownFade, {
    "lim-1 stop3 tp2 hold12": (dict(stop_atr=3.0, limit_atr=1.0, tp_atr=2.0), 12, 3),
    "lim-0.5 stop3 tp2 hold12": (dict(stop_atr=3.0, limit_atr=0.5, tp_atr=2.0), 12, 3),
    "lim-1.5 stop3 tp2 hold12": (dict(stop_atr=3.0, limit_atr=1.5, tp_atr=2.0), 12, 3),
    "lim-1 stop3 tp2 hold12 rank0.7": (dict(stop_atr=3.0, limit_atr=1.0, tp_atr=2.0, rank_min=0.7), 12, 3),
})
block("liquidity vacuum", S.LiquidityVacuumFade, {
    "mkt stop6 hold24": (dict(stop_atr=6.0), 24, 1),
    "mkt stop6 hold24 sp3": (dict(stop_atr=6.0, sp_mult=3.0), 24, 1),
}, extra=False)
