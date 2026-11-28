"""H12: intraday session hand-offs (UTC). Does the move of one session continue or reverse in the next?
A handful of natural windows only (no scanning). BTC and pooled universe following BTC's sign."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

pd.set_option("display.width", 250)
data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
ts = C.index
# (name, signal bar hour = last bar of the signal session, lookback hours, forward hours)
tests = [("US(13-21) -> Asia(21-06)", 20, 8, 9), ("Asia(00-08) -> Europe(08-13)", 7, 8, 5), ("Asia+EU(00-13) -> US(13-21)", 12, 13, 8),
         ("EU(07-13) -> US(13-21)", 12, 6, 8), ("US(13-21) -> next 24h", 20, 8, 24), ("24h to 00:00 -> next 24h", 23, 24, 24)]
rows = []
for nm, hr, look, fw in tests:
    for wk in ("weekday", "all"):
        idx = ts[(ts.hour == hr)]
        if wk == "weekday":
            idx = idx[idx.dayofweek < 5]
        w = (C[BTC] / C[BTC].shift(look) - 1).loc[idx]
        for delay in (0, 1):
            f = fwd_from_next_open(O[[BTC]], fw, delay)[BTC].loc[idx]
            d = pd.DataFrame({"w": w, "f": f}).dropna()
            fol = np.sign(d.w) * d.f
            vol = d.w.rolling(60, min_periods=30).std().shift(1)
            big = fol[(d.w.abs() > 1.0 * vol)]
            r = stats(fol, f"{nm} [{wk}] d={delay}", by_day=False)
            r["spearman"] = round(d.w.corr(d.f, method="spearman"), 3)
            r["big_n"] = len(big); r["big_mean"] = round(big.mean() * 1e4, 1); r["big_t"] = round(big.mean() / (big.std() / np.sqrt(len(big))), 2)
            r["yr"] = str({k: v[1] for k, v in by_year(fol).items()})
            rows.append(r)
show(rows)
