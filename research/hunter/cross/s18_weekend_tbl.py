"""Final table for the weekend idea: BTC and ETH following BTC's weekend sign, by threshold / year / side / delay."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 120)
data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
ts = C.index; t_idx = ts[(ts.dayofweek == 6) & (ts.hour == 21)]
w = (C[BTC] / C[BTC].shift(48) - 1).loc[t_idx]
rows = []
for sym in (BTC, ETH):
    for thr in (0.0, 0.005, 0.01):
        for delay in (0, 1):
            f = fwd_from_next_open(O[[sym]], 24, delay)[sym].loc[t_idx]
            d = pd.DataFrame({"w": w, "f": f})[T[sym].loc[t_idx].values].dropna()
            d = d[d.w.abs() >= thr]
            fol = np.sign(d.w) * d.f
            r = stats(fol, f"{sym[3:6]} thr={thr} d={delay}", by_day=False)
            r["long"] = f"{(d.w > 0).sum()}/{fol[d.w > 0].mean() * 1e4:.0f}"; r["short"] = f"{(d.w < 0).sum()}/{fol[d.w < 0].mean() * 1e4:.0f}"
            r["yr(n,bps,hit)"] = str({k: (v[0], float(v[1]), float(v[2])) for k, v in by_year(fol).items()})
            rows.append(r)
show(rows)
# bootstrap p-value for BTC thr=0 mean follow > 0 (sign-flip test)
f = fwd_from_next_open(O[[BTC]], 24)[BTC].loc[t_idx]
d = pd.DataFrame({"w": w, "f": f}).dropna(); fol = (np.sign(d.w) * d.f).values
rng = np.random.default_rng(7)
null = np.array([(fol * rng.choice([-1, 1], len(fol))).mean() for _ in range(20000)])
print("sign-flip p (BTC, all weekends):", (null >= fol.mean()).mean(), " n:", len(fol))
