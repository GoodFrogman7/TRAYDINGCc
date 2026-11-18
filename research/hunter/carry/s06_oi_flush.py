"""B: OI flush (positions closed/liquidated) -> rebound? Split by price direction during the flush."""
from lib import *
data = load()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
def mk(n, thr, kind="abs", pdir=None, side=1, pthr=0.0):
    def f(df, s):
        oi = df["oi"]
        d = oi / oi.shift(n) - 1
        if kind == "abs":
            m = d <= thr
        else:
            m = rrank(d, 720) <= thr
        r = df["close"] / df["close"].shift(n) - 1
        if pdir == "down": m &= r < -pthr
        if pdir == "up": m &= r > pthr
        return (m.astype(int) * side)
    return f
# distribution of OI changes
allv = pd.concat([(df["oi"] / df["oi"].shift(24) - 1)[df["tradable"]] for df in data.values()]).dropna()
print("OI 24h chg quantiles:", allv.quantile([.005, .01, .02, .05, .5, .95, .98, .99]).round(3).to_dict())
for h in (24, 48):
    print(f"### hold {h}h")
    for n, thr, kind in ((24, 0.02, "rank"), (24, -0.10, "abs"), (24, -0.15, "abs"), (24, -0.20, "abs"), (8, -0.10, "abs"), (72, -0.20, "abs")):
        for pdir in (None, "down", "up"):
            line(collect(data, mk(n, thr, kind, pdir), h, gap=h), f"OI {n}h chg {kind}<={thr} price {pdir} -> long {h}h")
