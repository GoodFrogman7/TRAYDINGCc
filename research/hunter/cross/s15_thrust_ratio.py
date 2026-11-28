"""H20: breadth thrust (share above 200h MA flips from <=lo to >=hi within 24h) -> continuation?
   H21: alt/BTC ratio breaks its 336h high (first in 48 bars) -> alt keeps outperforming BTC?"""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

pd.set_option("display.width", 280); pd.set_option("display.max_colwidth", 110)
data, P = panels()
C, O, Hi, Lo, T = P["close"], P["open"], P["high"], P["low"], P["trad"]
allc = list(C.columns); alts = [c for c in allc if c != BTC]
nT = T.sum(axis=1).astype(float).replace(0.0, np.nan)
ma = C.rolling(200, min_periods=200).mean(); br = ((C > ma) & T).sum(axis=1) / nT

print("== H20 breadth thrust ==")
rows = []
for lo_, hi_ in ((0.2, 0.8), (0.3, 0.7)):
    upc = (br >= hi_) & (br.rolling(24, min_periods=24).min() <= lo_)
    dnc = (br <= lo_) & (br.rolling(24, min_periods=24).max() >= hi_)
    for nm, c, sgn in (("thrust UP -> long", upc, 1), ("thrust DOWN -> short", dnc, -1)):
        first = c & ~c.shift(1, fill_value=False).rolling(48, min_periods=1).max().astype(bool)
        for h in (24, 72):
            for delay in (0, 1):
                F = fwd_from_next_open(O, h, delay)
                ev = stack_events(pd.DataFrame({a: first for a in allc}), F, T, sgn)
                r = stats(ev, f"{nm} {lo_}/{hi_} H={h} d={delay}"); r["events"] = int(first.sum()); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()}); rows.append(r)
show(rows)

print("\n== H21 alt/BTC ratio breakout ==")
ratio = C[alts].div(C[BTC], axis=0)
rows = []
for N in (168, 336):
    hi = ratio.shift(1).rolling(N, min_periods=N).max()
    up = ratio > hi
    first = up & ~up.shift(1, fill_value=False).rolling(48, min_periods=1).max().astype(bool)
    lo = ratio.shift(1).rolling(N, min_periods=N).min()
    dn = ratio < lo
    firstd = dn & ~dn.shift(1, fill_value=False).rolling(48, min_periods=1).max().astype(bool)
    for h in (72, 168):
        for delay in (0, 1):
            F = fwd_from_next_open(O, h, delay); Frel = F[alts].sub(F[BTC], axis=0)
            for nm, sig, sgn in (("ratio breakout long alt", first, 1), ("ratio breakdown short alt", firstd, -1)):
                ev = stack_events(sig, F[alts], T[alts], sgn); evr = stack_events(sig, Frel, T[alts], sgn)
                r = stats(ev, f"{nm} N={N} H={h} d={delay} RAW"); rr = stats(evr)
                r["rel_bps"] = rr.get("mean_bps"); r["rel_hit"] = rr.get("hit"); r["rel_t_day"] = rr.get("t_day")
                r["raw_yr"] = str({kk: v[1] for kk, v in by_year(ev).items()}); r["rel_yr"] = str({kk: v[1] for kk, v in by_year(evr).items()}); rows.append(r)
show(rows)
