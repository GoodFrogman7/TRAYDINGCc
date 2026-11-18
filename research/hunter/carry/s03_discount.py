"""Hypothesis A: deep negative premium (perp at a discount = shorts crowded / forced selling) -> bounce."""
from lib import *
data = load()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)

def sig(ma, q, lvl=None, win=720):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        rk = rrank(pm, win)
        m = rk <= q
        if lvl is not None:
            m &= pm <= lvl
        return m.astype(int)
    return f

for ma in (1, 4, 8):
    for q in (0.01, 0.02, 0.05):
        for h in (12, 24, 48):
            ev = collect(data, sig(ma, q), h, gap=h)
            study(ev, label=f"discount long: prem_ma{ma} rank30d<={q}, hold {h}h, declustered {h}h")
