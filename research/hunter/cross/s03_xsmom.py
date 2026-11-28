"""H3: cross-sectional relative strength within the month's top 10. Sampled once per day at 00:00 UTC close
(bar 23:00), entry at next open. Returns reported raw and relative to the equal-weight basket."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
samp = C.index[C.index.hour == 23]            # decide at the close of the 23:00 bar
rows = []
for L in [24, 72, 168, 336, 720]:
    mom = (C / C.shift(L) - 1).where(T)
    rk = mom.rank(axis=1, ascending=False)     # 1 = strongest
    n = mom.notna().sum(axis=1)
    for H in [24, 72, 168]:
        F = fwd_from_next_open(O, H)
        Fb = F.where(T).mean(axis=1)           # basket forward return
        for nm, sel in [("top2", rk <= 2), ("bot2", rk.gt(n - 2, axis=0))]:
            sel = sel & T & (n >= 8).values[:, None]
            f = F.where(sel).loc[samp]
            raw = f.mean(axis=1).dropna()
            rel = (f.mean(axis=1) - Fb.loc[samp]).dropna()
            def ts(x):
                # overlapping daily samples of H-hour returns: deflate t by sqrt(H/24)
                return round(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) / np.sqrt(H / 24), 2)
            rows.append(dict(L=L, H=H, leg=nm, n_days=len(raw), raw_bps=round(raw.mean() * 1e4, 1),
                             rel_bps=round(rel.mean() * 1e4, 1), rel_hit=round((rel > 0).mean(), 3), t_rel_adj=ts(rel),
                             **{f"rel{y}": round(rel[rel.index.year == y].mean() * 1e4, 1) for y in (2022, 2023, 2024)}))
show(rows)
