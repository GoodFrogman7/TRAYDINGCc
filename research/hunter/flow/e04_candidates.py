"""Design-window engine check of the candidate rules: default + two neighbours each, fees x2, Guardian on."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
from desk.engine.core import Costs, Risk

def block(title, cls, variants, vb=1):
    rows = []
    for nm, (p, mh) in variants.items():
        st = cls(); st.valid_bars = vb
        rows.append(E.check(st, p, label=nm, max_hold=mh))
    nm0, (p0, mh0) = next(iter(variants.items()))
    st = cls(); st.valid_bars = vb
    rows.append(E.check(st, p0, label=nm0 + " | fees x2", max_hold=mh0, costs=Costs(fee_mult=2.0)))
    st = cls(); st.valid_bars = vb
    rows.append(E.check(st, p0, label=nm0 + " | slip x2", max_hold=mh0, costs=Costs(slip_mult=2.0)))
    st = cls(); st.valid_bars = vb
    rows.append(E.check(st, p0, label=nm0 + " | no guardian", max_hold=mh0, risk=Risk(guardian=False)))
    print(f"\n##### {title}")
    E.table(rows)

block("weekend dump short", S.WeekendDumpShort, {
    "z0.75 h21 stop3 hold24": (dict(z=0.75), 24),
    "z1.0 h21 stop3 hold24": (dict(z=1.0), 24),
    "z0.75 h17": (dict(z=0.75, hour=17), 24),
    "z0.75 h23": (dict(z=0.75, hour=23), 24),
    "z0.75 stop2.5": (dict(z=0.75, stop_atr=2.5), 24),
    "z0.75 stop3.5": (dict(z=0.75, stop_atr=3.5), 24),
    "z0.75 hold12": (dict(z=0.75), 12),
    "z0.75 BOTH sides": (dict(z=0.75, both=True), 24),
})
block("stress bid (alt held while BTC dumped)", S.StressBid, {
    "zb3 za-1 stop3 hold24": (dict(), 24),
    "hold12": (dict(), 12),
    "stop2.5": (dict(stop_atr=2.5), 24),
    "stop4": (dict(stop_atr=4.0), 24),
    "zb2.5": (dict(z_btc=2.5), 24),
    "zb3.5": (dict(z_btc=3.5), 24),
    "za-0.5": (dict(z_alt=-0.5), 24),
})
