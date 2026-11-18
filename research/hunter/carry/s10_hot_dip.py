"""G': rich premium regime + price makes a new N-bar low -> LONG (dip in a hot market gets bought).
Controls: same dip without rich premium."""
from lib import *
from desk.strategies import ta
data = load()
def mk(pma, lo, hi, n, kind="donch"):
    def f(df, s):
        pm = df["premium"].rolling(pma, min_periods=pma).mean() * 1e4
        c = df["close"]
        if kind == "donch":
            m = c < ta.donchian_low(df, n)
        else:  # drop of n-bar return below -kind
            m = (c / c.shift(n) - 1) <= -kind
        m &= (pm > lo) & (pm <= hi)
        return m.astype(int)
    return f
print("### 24h hold, donchian24 low break, by premium(24h mean) bucket in bps")
for lo, hi in ((-1e9, -8), (-8, -3), (-3, 0), (0, 3), (3, 8), (8, 15), (15, 1e9)):
    line(collect(data, mk(24, lo, hi, 24), 24, gap=24), f"don24 low & prem_ma24 in ({lo},{hi}]")
print("### robustness: premium window / dip window / hold")
for pma, n, h in ((24, 24, 12), (24, 24, 48), (24, 48, 24), (24, 12, 24), (72, 24, 24), (8, 24, 24)):
    line(collect(data, mk(pma, 8, 1e9, n), h, gap=h), f"don{n} low & prem_ma{pma}>8 hold {h}")
