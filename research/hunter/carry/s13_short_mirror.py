"""Mirror of the dip table: at a new 24h HIGH, forward SHORT return by premium bucket; plus two theory-driven shorts."""
from lib import *
from desk.strategies import ta
data = load()
def hi_brk(pma, lo, hi, jump=False):
    def f(df, s):
        pm = df["premium"].rolling(pma, min_periods=pma).mean() * 1e4
        if jump:
            pm = pm - df["premium"].rolling(72, min_periods=72).mean() * 1e4
        m = (df["close"] > ta.donchian_high(df, 24)) & (pm > lo) & (pm <= hi)
        return -m.astype(int)
    return f
print("### new 24h high -> SHORT 12h, by prem_ma8 bucket")
for lo, hi in ((-1e9, -8), (-8, -3), (-3, 3), (3, 8), (8, 15), (15, 30), (30, 1e9)):
    line(collect(data, hi_brk(8, lo, hi), 12, gap=12), f"don24 high & prem_ma8 in ({lo},{hi}] short 12h")
print("### new 24h high -> SHORT 12h, by premium JUMP (prem_ma4 - prem_ma72) bucket")
for lo, hi in ((-1e9, -5), (-5, 5), (5, 10), (10, 20), (20, 1e9)):
    line(collect(data, hi_brk(4, lo, hi, jump=True), 12, gap=12), f"don24 high & prem jump in ({lo},{hi}] short 12h")
def deadcat(pthr):
    def f(df, s):
        c = df["close"]
        m = (c < c.rolling(168).mean()) & ((c / c.shift(72) - 1) <= -0.08) & (df["premium"].rolling(8).mean() * 1e4 >= pthr)
        return -m.astype(int)
    return f
print("### S1 dead-cat: downtrend (-8%/72h, below 168h mean) but 8h premium rich -> SHORT")
for h in (12, 24):
    for pthr in (3, 8):
        line(collect(data, deadcat(pthr), h, gap=h), f"deadcat prem_ma8>={pthr} short {h}h")
