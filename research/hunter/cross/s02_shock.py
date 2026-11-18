"""H2: market-wide shock (basket of the month's top 10 moves k sigma in one hour) -> fade or follow in each member?"""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
r1 = C.pct_change()
basket = r1.where(T).mean(axis=1)                 # equal-weight hourly return of the tradable set
nmem = T.sum(axis=1)
vol = basket.rolling(168, min_periods=100).std().shift(1)
z = basket / vol
allc = list(C.columns)
rows = []
for k in [3.0, 4.0, 5.0]:
    for side, nm in [(-1, "down-shock -> LONG"), (1, "up-shock -> SHORT")]:
        big = (z * side > k) & (nmem >= 8)
        for h in [1, 3, 6, 12, 24, 48]:
            for delay in [0, 1]:
                F = fwd_from_next_open(O, h, delay)
                sig = pd.DataFrame({a: big for a in allc})
                ev = stack_events(sig, F, T, -side)
                rows.append(stats(ev, f"{nm} k={k} h={h} d={delay}"))
show(rows)
print()
for k in [3.0, 4.0]:
    for side, nm in [(-1, "down-shock -> LONG"), (1, "up-shock -> SHORT")]:
        big = (z * side > k) & (nmem >= 8)
        for h in [6, 24]:
            F = fwd_from_next_open(O, h, 0)
            sig = pd.DataFrame({a: big for a in allc})
            ev = stack_events(sig, F, T, -side)
            print(nm, k, h, by_year(ev), "distinct hours:", int(big.sum()))
