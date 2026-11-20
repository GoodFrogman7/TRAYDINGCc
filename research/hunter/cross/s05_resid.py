"""H6: idiosyncratic (vs basket) moves: short-horizon cross-sectional reversal or continuation?
   H7: big 24h idiosyncratic breakouts (event) -> continuation?
   H8: ETH/BTC ratio as alt risk-on signal."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
n_tr = T.sum(axis=1)

print("== H6: every-bar cross-sectional rank on L-hour return rel. to basket; fwd H rel. return of extreme names ==")
rows = []
for L in [1, 4, 12]:
    ret = (C / C.shift(L) - 1).where(T)
    rel = ret.sub(ret.mean(axis=1), axis=0)
    rk = rel.rank(axis=1, ascending=False)
    cnt = rel.notna().sum(axis=1)
    for H in [1, 4, 12, 24]:
        F = fwd_from_next_open(O, H)
        Fb = F.where(T).mean(axis=1)
        Frel = F.sub(Fb, axis=0)
        for nm, sel in [("top1", rk == 1), ("bot1", rk.eq(cnt, axis=0))]:
            sel = sel & T & (cnt >= 8).values[:, None]
            ev_rel = stack_events(sel, Frel, T); ev_raw = stack_events(sel, F, T)
            s = stats(ev_rel, f"L={L} H={H} {nm}")
            s["raw_bps"] = round(ev_raw.mean() * 1e4, 1)
            rows.append(s)
show(rows)

print("\n== H7: idiosyncratic 24h move z-score event (rel. return vs basket / trailing 30d std of rel 24h ret) ==")
rel24 = (C / C.shift(24) - 1)
bas24 = rel24.where(T).mean(axis=1)
rel24 = rel24.sub(bas24, axis=0)
sd = rel24.rolling(720, min_periods=360).std().shift(24)
z = rel24 / sd
rows = []
for k in [2.0, 3.0]:
    for side, nm in [(1, "idio UP"), (-1, "idio DOWN")]:
        cond = (z * side > k)
        first = cond & ~cond.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)   # first trigger in 24 bars
        for H in [6, 24, 72, 168]:
            for delay in [0, 1]:
                F = fwd_from_next_open(O, H, delay)
                Frel = F.sub(F.where(T).mean(axis=1), axis=0)
                ev = stack_events(first, F, T, side); evr = stack_events(first, Frel, T, side)
                s = stats(ev, f"{nm} k={k} H={H} d={delay} FOLLOW raw")
                s["rel_bps"] = round(evr.mean() * 1e4, 1); s["rel_t"] = stats(evr).get("t_day")
                if delay == 0 and H in (24, 72):
                    s["yr"] = str(by_year(ev))
                rows.append(s)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 120)
show(rows)

print("\n== H8: ETH/BTC ratio momentum -> fwd alt basket (ex BTC, ETH) minus BTC, sampled daily ==")
ratio = C[ETH] / C[BTC]
samp = C.index[C.index.hour == 23]
alts = [c for c in C.columns if c not in (BTC, ETH)]
rows = []
for L in [72, 168, 336]:
    m = ratio / ratio.shift(L) - 1
    for H in [24, 72, 168]:
        F = fwd_from_next_open(O, H)
        fa = F[alts].where(T[alts]).mean(axis=1); fb = F[BTC]
        d = pd.DataFrame({"m": m, "alt": fa, "sp": fa - fb}).loc[samp].dropna()
        for nm, g in [("ETHBTC up", d[d.m > 0]), ("ETHBTC down", d[d.m <= 0])]:
            rows.append(dict(L=L, H=H, state=nm, n=len(g), alt_raw_bps=round(g.alt.mean() * 1e4, 1), alt_minus_btc_bps=round(g.sp.mean() * 1e4, 1),
                             t_adj=round(g.sp.mean() / (g.sp.std() / np.sqrt(len(g))) / np.sqrt(H / 24), 2),
                             **{f"sp{y}": round(g.sp[g.index.year == y].mean() * 1e4, 1) for y in (2022, 2023, 2024)}))
show(rows)
