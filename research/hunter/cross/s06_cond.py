"""H9: relative-strength legs conditional on market regime (breadth / basket trend), raw returns.
   H10: per-coin channel breakout conditional on breadth (participation).
   H11: weekend move -> Monday reversal/continuation."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

pd.set_option("display.width", 250)
data, P = panels()
C, O, H_, L_, T = P["close"], P["open"], P["high"], P["low"], P["trad"]
samp = C.index[C.index.hour == 23]
nT = T.sum(axis=1).astype(float).replace(0.0, np.nan)

def breadth(n):
    ma = C.rolling(n, min_periods=n).mean()
    return ((C > ma) & T).sum(axis=1) / nT

print("== H9: top2 / bot2 by L-hour return; RAW fwd return by regime (breadth over 200h / 480h MA), sampled daily ==")
rows = []
for L in [168, 336]:
    mom = (C / C.shift(L) - 1).where(T)
    rk = mom.rank(axis=1, ascending=False); n = mom.notna().sum(axis=1)
    for man in [200, 480]:
        br = breadth(man)
        for Hh in [72, 168]:
            F = fwd_from_next_open(O, Hh)
            for leg, sel, sgn in [("LONG top2", rk <= 2, 1), ("SHORT bot2", rk.gt(n - 2, axis=0), -1)]:
                for rg, cond in [("breadth>=0.6", br >= 0.6), ("breadth<=0.4", br <= 0.4), ("mid", (br > 0.4) & (br < 0.6))]:
                    s = (sel & T).mul(cond, axis=0) & (n >= 8).values[:, None]
                    f = (sgn * F.where(s)).loc[samp].mean(axis=1).dropna()
                    if len(f) < 20: continue
                    rows.append(dict(L=L, ma=man, H=Hh, leg=leg, regime=rg, n_days=len(f), raw_bps=round(f.mean() * 1e4, 1), hit=round((f > 0).mean(), 3),
                                     t_adj=round(f.mean() / (f.std() / np.sqrt(len(f))) / np.sqrt(Hh / 24), 2),
                                     **{f"y{y}": round(f[f.index.year == y].mean() * 1e4, 1) for y in (2022, 2023, 2024)},
                                     **{f"n{y}": int((f.index.year == y).sum()) for y in (2022, 2023, 2024)}))
show(rows)

print("\n== H10: 96h channel breakout (first in 24 bars), fwd by breadth(200h) at signal ==")
rows = []
br = breadth(200)
for N in [96]:
    hi = H_.shift(1).rolling(N, min_periods=N).max(); lo = L_.shift(1).rolling(N, min_periods=N).min()
    up = C > hi; dn = C < lo
    upf = up & ~up.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)
    dnf = dn & ~dn.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)
    for Hh in [24, 72]:
        for delay in [0, 1]:
            F = fwd_from_next_open(O, Hh, delay)
            for nm, sig, sgn in [("UP breakout long", upf, 1), ("DOWN breakdown short", dnf, -1)]:
                for rg, cond in [("all", br >= 0), ("br>=0.7", br >= 0.7), ("br 0.3-0.7", (br > 0.3) & (br < 0.7)), ("br<=0.3", br <= 0.3)]:
                    ev = stack_events(sig.mul(cond, axis=0).astype(bool), F, T, sgn)
                    s = stats(ev, f"{nm} H={Hh} d={delay} {rg}")
                    s["yr"] = str({k: v[:2] for k, v in by_year(ev).items()})
                    rows.append(s)
show(rows)

print("\n== H11: weekend basket return (Fri 21:00 -> Sun 21:00 UTC) vs next 24h/48h (enter Sun 22:00 open) ==")
bas_o = O.where(T)
ts = C.index
sun = ts[(ts.dayofweek == 6) & (ts.hour == 21)]
rows = []
for sym_set, nm in [(None, "basket"), ([BTC], "BTC")]:
    recs = []
    for t in sun:
        t0 = t - pd.Timedelta(hours=48)
        if t0 not in C.index: continue
        cols = [c for c in C.columns if T.at[t, c]] if sym_set is None else sym_set
        wk = (C.loc[t, cols] / C.loc[t0, cols] - 1).mean()
        t1 = t + pd.Timedelta(hours=1)
        for Hh in (24, 48):
            t2 = t1 + pd.Timedelta(hours=Hh)
            if t2 in O.index:
                recs.append((t, Hh, wk, (O.loc[t2, cols] / O.loc[t1, cols] - 1).mean()))
    d = pd.DataFrame(recs, columns=["t", "H", "wk", "f"]).dropna()
    for Hh in (24, 48):
        g = d[d.H == Hh]
        for thr in (0.0, 0.03):
            big = g[g.wk.abs() > thr]
            fade = -np.sign(big.wk) * big.f
            rows.append(dict(set=nm, H=Hh, thr=thr, n=len(big), fade_bps=round(fade.mean() * 1e4, 1), hit=round((fade > 0).mean(), 3),
                             t=round(fade.mean() / (fade.std() / np.sqrt(len(fade))), 2), corr=round(g.wk.corr(g.f), 3)))
show(rows)
