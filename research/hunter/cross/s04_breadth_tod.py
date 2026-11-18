"""H4: breadth (share of the month's top 10 above a trailing MA) as a regime filter.
   H5: hour-of-day / day-of-week effects."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
r1o = O.shift(-2) / O.shift(-1) - 1     # return of the NEXT bar open->open (tradeable after signal at close t)
bas_next = r1o.where(T).mean(axis=1)
samp = C.index[C.index.hour == 23]

print("== breadth regime: forward basket return (bps) by breadth bucket, sampled daily ==")
rows = []
for n in [72, 200, 480]:
    ma = C.rolling(n, min_periods=n).mean()
    above = ((C > ma) & T).astype(float)
    br = above.sum(axis=1) / T.sum(axis=1).astype(float).replace(0.0, np.nan)
    for H in [24, 72, 168]:
        Fb = fwd_from_next_open(O, H).where(T).mean(axis=1)
        d = pd.DataFrame({"br": br, "f": Fb}).loc[samp].dropna()
        for lo, hi, nm in [(-0.01, 0.2, "<=20%"), (0.2, 0.5, "20-50%"), (0.5, 0.79, "50-79%"), (0.79, 1.0, ">=80%")]:
            g = d[(d.br > lo) & (d.br <= hi)]
            rows.append(dict(ma=n, H=H, bucket=nm, n=len(g), mean_bps=round(g.f.mean() * 1e4, 1), hit=round((g.f > 0).mean(), 3),
                             t_adj=round(g.f.mean() / (g.f.std() / np.sqrt(len(g))) / np.sqrt(H / 24), 2),
                             **{f"y{y}": round(g.f[g.index.year == y].mean() * 1e4, 1) for y in (2022, 2023, 2024)}))
show(rows)

print("\n== hour of day (UTC): mean open->open return of the bar starting at that hour, bps ==")
ro = (O.shift(-1) / O - 1)          # return of bar t itself, open(t)->open(t+1)
bas = ro.where(T).mean(axis=1)
for nm, s in [("basket", bas), ("BTC", ro[BTC].where(T[BTC])), ("alts ex BTC/ETH", ro.drop(columns=[BTC, ETH]).where(T.drop(columns=[BTC, ETH])).mean(axis=1))]:
    s = s.dropna()
    g = s.groupby(s.index.hour)
    tab = pd.DataFrame({"mean_bps": g.mean() * 1e4, "t": g.mean() / (g.std() / np.sqrt(g.count())),
                        **{f"y{y}": s[s.index.year == y].groupby(s[s.index.year == y].index.hour).mean() * 1e4 for y in (2022, 2023, 2024)}}).round(2)
    print(nm); print(tab.T.to_string())

print("\n== day of week (0=Mon): mean daily (00:00->00:00) basket return, bps ==")
for nm, s in [("basket", bas), ("BTC", ro[BTC].where(T[BTC]))]:
    d = s.dropna().resample("D").sum()
    g = d.groupby(d.index.dayofweek)
    tab = pd.DataFrame({"mean_bps": g.mean() * 1e4, "t": g.mean() / (g.std() / np.sqrt(g.count())),
                        **{f"y{y}": d[d.index.year == y].groupby(d[d.index.year == y].index.dayofweek).mean() * 1e4 for y in (2022, 2023, 2024)}}).round(1)
    print(nm); print(tab.T.to_string())
