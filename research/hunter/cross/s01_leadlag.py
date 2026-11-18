"""H1: after a large BTC hourly move, do alts that have not moved catch up over the next 1-6 bars?"""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
r1 = C.pct_change()
btc = r1[BTC]
vol = btc.rolling(168, min_periods=100).std().shift(1)          # trailing hourly vol, excl. current bar
z = btc / vol
alts = [c for c in C.columns if c != BTC]
# trailing beta of each alt to BTC (720h), lagged one bar
cov = r1[alts].rolling(720, min_periods=300).cov(btc)
beta = cov.div(btc.rolling(720, min_periods=300).var(), axis=0).shift(1)
resid = r1[alts] - beta.mul(btc, axis=0)       # alt move not explained by BTC this hour (negative when BTC up & alt lagged)

print("== basic lag correlations: corr(alt r[t+1], btc r[t]) pooled tradable ==")
for lag in [1, 2, 3]:
    x = btc.shift(lag)
    cs = []
    for a in alts:
        m = T[a]
        if m.sum() > 2000:
            cs.append(r1[a][m].corr(x[m]))
    print(lag, round(np.mean(cs), 4))
print("corr(btc r[t+1], btc r[t]) =", round(btc.corr(btc.shift(1)), 4), " corr(btc r[t+1], eth r[t]) =", round(btc.corr(r1[ETH].shift(1)), 4),
      " corr(eth r[t+1], btc r[t]) =", round(r1[ETH].corr(btc.shift(1)), 4))

rows = []
for k in [2.0, 3.0, 4.0]:
    big = (z.abs() > k)
    sgn = np.sign(btc)
    for h in [1, 3, 6]:
        for delay in [0, 1]:
            F = fwd_from_next_open(O[alts], h, delay)
            # all alts, trade in BTC's direction
            sig = pd.DataFrame({a: big for a in alts})
            S = pd.DataFrame({a: sgn for a in alts})
            ev = stack_events(sig, F, T[alts], S)
            d = stats(ev, f"all alts follow BTC k={k} h={h} d={delay}")
            rows.append(d)
            # only laggards: alt residual opposite to BTC by > 0.5 * |btc move|
            lag = resid.mul(sgn, axis=0) < -0.5 * btc.abs().values[:, None]
            ev = stack_events(sig & lag, F, T[alts], S)
            rows.append(stats(ev, f"  laggards only   k={k} h={h} d={delay}"))
show(rows)

print("\n== BTC itself after its own big move (continuation in BTC dir) ==")
rows = []
for k in [2.0, 3.0, 4.0]:
    big = (z.abs() > k) & T[BTC]
    for h in [1, 3, 6, 24]:
        F = fwd_from_next_open(O[[BTC]], h)[BTC]
        ev = (F * np.sign(btc))[big]
        rows.append(stats(ev, f"BTC k={k} h={h}"))
show(rows)

print("\n== laggards by year / side, k=3 h=3 ==")
k, h = 3.0, 3
big = (z.abs() > k); sgn = np.sign(btc)
F = fwd_from_next_open(O[alts], h)
sig = pd.DataFrame({a: big for a in alts}); S = pd.DataFrame({a: sgn for a in alts})
lag = resid.mul(sgn, axis=0) < -0.5 * btc.abs().values[:, None]
ev = stack_events(sig & lag, F, T[alts], S)
print(by_year(ev))
for side, nm in [(1, "BTC up (long alts)"), (-1, "BTC down (short alts)")]:
    sg = pd.DataFrame({a: big & (sgn == side) for a in alts})
    print(nm, stats(stack_events(sg & lag, F, T[alts], S)))
