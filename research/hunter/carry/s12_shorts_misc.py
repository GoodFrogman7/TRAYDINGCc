"""Looking for a short / two-sided idea, and the long-only premium-confirmed breakout."""
from lib import *
from desk.strategies import ta
data = load()
def flip_up_short(ma):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        m = (pm > 0) & (pm.shift(1) <= 0) & (pm.shift(1).rolling(ma).max() <= 0)
        return -m.astype(int)
    return f
def flip_dn_long(ma):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        m = (pm < 0) & (pm.shift(1) >= 0) & (pm.shift(1).rolling(ma).min() >= 0)
        return m.astype(int)
    return f
print("### a) flips of slow premium average, faded")
for ma in (48, 72):
    for h in (12, 24, 48):
        line(collect(data, flip_up_short(ma), h, gap=h), f"prem_ma{ma} flips UP after {ma}h<=0 -> SHORT {h}h")
        line(collect(data, flip_dn_long(ma), h, gap=h), f"prem_ma{ma} flips DOWN after {ma}h>=0 -> LONG {h}h")

def trapped(oithr, pthr):
    def f(df, s):
        c = df["close"]; oi = df["oi"]
        m = ((c / c.shift(24) - 1) <= -pthr) & ((oi / oi.shift(24) - 1) >= oithr) & (df["premium"].rolling(8).mean() > 0)
        return -m.astype(int)
    return f
def blowoff(oithr, pthr):
    def f(df, s):
        c = df["close"]; oi = df["oi"]
        m = ((c / c.shift(24) - 1) >= pthr) & ((oi / oi.shift(24) - 1) >= oithr) & (df["premium"].rolling(8).mean() > 0.0010)
        return -m.astype(int)
    return f
print("### d) trapped longs: price -3%/24h, OI up, premium still positive -> SHORT")
for h in (12, 24):
    line(collect(data, trapped(0.05, 0.03), h, gap=h), f"trapped longs short {h}h")
    line(collect(data, trapped(0.10, 0.05), h, gap=h), f"trapped longs (stronger) short {h}h")
print("### g) blow-off: price +8%/24h, OI +20%/24h, premium rich -> SHORT")
for h in (12, 24, 48):
    line(collect(data, blowoff(0.20, 0.08), h, gap=h), f"blowoff short {h}h")

def conf_brk(n, lo, hi):
    def f(df, s):
        pm = df["premium"].rolling(24, min_periods=24).mean() * 1e4
        m = (df["close"] > ta.donchian_high(df, n)) & (pm > lo) & (pm <= hi)
        return m.astype(int)
    return f
print("### long-only breakout by premium bucket (trend-filter hypothesis)")
for h in (48, 96):
    for lo, hi in ((-1e9, -2), (-2, 2), (2, 6), (6, 1e9)):
        line(collect(data, conf_brk(96, lo, hi), h, gap=h), f"don96 high break & prem_ma24 in ({lo},{hi}] long {h}h")
