"""H13: market-wide shock traded in the direction of the breadth regime (vs. the no-shock baseline).
   H14: breakout x breadth bucket robustness.  H15: cross-sectional premium (crowding) rank."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

pd.set_option("display.width", 280); pd.set_option("display.max_colwidth", 100)
data, P = panels()
C, O, Hi, Lo, T = P["close"], P["open"], P["high"], P["low"], P["trad"]
nT = T.sum(axis=1).astype(float).replace(0.0, np.nan)
def breadth(n):
    ma = C.rolling(n, min_periods=n).mean()
    return ((C > ma) & T).sum(axis=1) / nT
allc = list(C.columns)

print("== H13: shock hour (|basket z|>k) -> trade every member in the REGIME direction (breadth480>=0.6 long, <=0.4 short) ==")
r1 = C.pct_change(); basket = r1.where(T).mean(axis=1)
z = basket / basket.rolling(168, min_periods=100).std().shift(1)
br = breadth(480)
reg = pd.Series(np.where(br >= 0.6, 1, np.where(br <= 0.4, -1, 0)), index=C.index)
rows = []
for h in (12, 24, 48):
    F = fwd_from_next_open(O, h)
    S = pd.DataFrame({a: reg for a in allc})
    base = stack_events(pd.DataFrame({a: reg != 0 for a in allc}), F, T, S)
    rows.append({**stats(base, f"BASELINE every hour, regime dir H={h}"), "yr": str({k: v[1] for k, v in by_year(base).items()})})
    for k in (3.0, 4.0):
        for nm, cond in (("up-shock", z > k), ("down-shock", z < -k), ("any shock", z.abs() > k)):
            for delay in (0, 1):
                Fd = fwd_from_next_open(O, h, delay)
                ev = stack_events(pd.DataFrame({a: cond & (reg != 0) for a in allc}), Fd, T, S)
                r = stats(ev, f"{nm} k={k} H={h} d={delay}"); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()})
                for sd, lab in ((1, "L"), (-1, "S")):
                    e2 = stack_events(pd.DataFrame({a: cond & (reg == sd) for a in allc}), Fd, T, sd)
                    r[f"{lab}_n"] = len(e2); r[f"{lab}_bps"] = round(e2.mean() * 1e4, 1) if len(e2) else np.nan
                rows.append(r)
show(rows)

print("\n== H14: N-bar breakout long (first in 24 bars) by breadth bucket: robustness over N and MA ==")
rows = []
for N in (72, 96, 168):
    hi = Hi.shift(1).rolling(N, min_periods=N).max()
    up = C > hi
    upf = up & ~up.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)
    for man in (100, 200, 480):
        b = breadth(man)
        F = fwd_from_next_open(O, 72)
        for rg, cond in (("<=0.3", b <= 0.3), ("0.3-0.7", (b > 0.3) & (b < 0.7)), (">=0.7", b >= 0.7)):
            ev = stack_events(upf.mul(cond, axis=0).astype(bool), F, T, 1)
            r = stats(ev, f"N={N} ma={man} breadth {rg} H=72"); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()}); rows.append(r)
show(rows)

print("\n== H15: cross-sectional premium rank (trailing 24h mean premium), daily sample: fwd rel. return of richest2 / cheapest2 ==")
prem = P["premium"].rolling(24, min_periods=12).mean().where(T)
rk = prem.rank(axis=1, ascending=False); n = prem.notna().sum(axis=1)
samp = C.index[C.index.hour == 23]
rows = []
for H in (24, 72, 168):
    F = fwd_from_next_open(O, H); Fb = F.where(T).mean(axis=1)
    for nm, sel in (("richest2", rk <= 2), ("cheapest2", rk.gt(n - 2, axis=0))):
        sel = sel & T & (n >= 8).values[:, None]
        f = F.where(sel).loc[samp]
        rel = (f.mean(axis=1) - Fb.loc[samp]).dropna(); raw = f.mean(axis=1).dropna()
        rows.append(dict(H=H, leg=nm, n_days=len(rel), raw_bps=round(raw.mean() * 1e4, 1), rel_bps=round(rel.mean() * 1e4, 1),
                         t_adj=round(rel.mean() / (rel.std() / np.sqrt(len(rel))) / np.sqrt(H / 24), 2),
                         **{f"rel{y}": round(rel[rel.index.year == y].mean() * 1e4, 1) for y in (2022, 2023, 2024)}))
show(rows)
