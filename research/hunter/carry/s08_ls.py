"""E: ls_ratio (share of accounts net long). Fast changes split by price direction; level extremes vs own history."""
from lib import *
data = load()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
def mk(kind, thr, pdir=None, side=1, n=24):
    def f(df, s):
        ls = df["ls_ratio"]
        d = ls - ls.shift(n)
        if kind == "d_lo": m = d <= -thr
        if kind == "d_hi": m = d >= thr
        if kind == "lvl_lo": m = rrank(ls, 720) <= thr
        if kind == "lvl_hi": m = rrank(ls, 720) >= 1 - thr
        r = df["close"] / df["close"].shift(n) - 1
        if pdir == "down": m &= r < -0.02
        if pdir == "up": m &= r > 0.02
        if pdir == "flat": m &= r.abs() <= 0.02
        return m.astype(int) * side
    return f
allv = pd.concat([(df["ls_ratio"] - df["ls_ratio"].shift(24))[df["tradable"]] for df in data.values()]).dropna()
print("ls 24h diff quantiles:", allv.quantile([.01, .02, .05, .5, .95, .98, .99]).round(3).to_dict())
h = 24
for kind, thr in (("d_lo", 0.04), ("d_hi", 0.04), ("lvl_lo", 0.05), ("lvl_hi", 0.05)):
    for pdir in (None, "down", "up", "flat"):
        line(collect(data, mk(kind, thr, pdir), h, gap=h), f"ls {kind} {thr} price24h {pdir} -> LONG {h}h (negate for short)")
