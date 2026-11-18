"""Final design-window engine checks for the remaining candidates (default + neighbours)."""
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

H = dict(stop_atr=3.0, limit_atr=1.5, tp_atr=2.0, rank_min=0.7)
block("hot breakdown, limit 1.5 ATR below, rank>0.7", S.HotVolBreakdownFade, {
    "lim-1.5 rank0.7 stop3 tp2 hold12": (H, 12, 3),
    "n=36": ({**H, "n": 36}, 12, 3),
    "n=72": ({**H, "n": 72}, 12, 3),
    "rank0.5": ({**H, "rank_min": 0.5}, 12, 3),
    "rank0.85": ({**H, "rank_min": 0.85}, 12, 3),
    "lim-1.0": ({**H, "limit_atr": 1.0}, 12, 3),
    "lim-2.0": ({**H, "limit_atr": 2.0}, 12, 3),
    "tp none hold12": ({**H, "tp_atr": None}, 12, 3),
    "hold24": (H, 24, 3),
})
V = dict(sp_mult=3.0, stop_atr=6.0)
block("liquidity vacuum sp>=3x", S.LiquidityVacuumFade, {
    "sp3 stop6 hold24": (V, 24, 1),
    "sp3 stop4 hold24": ({**V, "stop_atr": 4.0}, 24, 1),
    "sp3 stop6 hold12": (V, 12, 1),
    "sp2.5": ({**V, "sp_mult": 2.5}, 24, 1),
    "sp4": ({**V, "sp_mult": 4.0}, 24, 1),
    "drop1.5": ({**V, "drop_atr": 1.5}, 24, 1),
    "drop2.5": ({**V, "drop_atr": 2.5}, 24, 1),
})
W = dict(z=0.75, dirn=1)
block("weekend pump LONG", S.WeekendDumpShort, {
    "long z0.75 h21 stop3 hold24": (W, 24, 1),
    "long z1.0": ({**W, "z": 1.0}, 24, 1),
    "long z1.25": ({**W, "z": 1.25}, 24, 1),
    "long h17": ({**W, "hour": 17}, 24, 1),
    "long h23": ({**W, "hour": 23}, 24, 1),
    "long hold12": (W, 12, 1),
})
block("weekend dump SHORT extra neighbours", S.WeekendDumpShort, {
    "short z1.25 h21": (dict(z=1.25), 24, 1),
    "short z1.0 h17": (dict(z=1.0, hour=17), 24, 1),
    "short z1.0 h23": (dict(z=1.0, hour=23), 24, 1),
    "short z0.75 hold48": (dict(z=0.75), 48, 1),
}, extra=False)
