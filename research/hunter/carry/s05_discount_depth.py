"""A: dose-response of the discount depth (absolute bps and trailing z)."""
from lib import *
data = load()
H = 24
def mk(ma, lo, hi, kind):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        if kind == "abs":
            x = pm * 1e4
        else:
            mu = pm.rolling(720, min_periods=360).median()
            sd = df["premium"].rolling(720, min_periods=360).std()
            x = (pm - mu) / sd
        return ((x > lo) & (x <= hi)).astype(int)
    return f
print("### absolute premium level buckets (bps), 24h hold, declustered 24h")
for ma in (1, 8, 24):
    for lo, hi in ((-1e9, -30), (-30, -20), (-20, -12), (-12, -8), (-8, -5)):
        line(collect(data, mk(ma, lo, hi, "abs"), H, gap=H), f"prem_ma{ma} in ({lo},{hi}] bps")
print("### z buckets (pm - median30d)/std30d of hourly premium")
for ma in (8,):
    for lo, hi in ((-1e9, -4), (-4, -3), (-3, -2), (-2, -1.5)):
        line(collect(data, mk(ma, lo, hi, "z"), H, gap=H), f"prem_ma{ma} z in ({lo},{hi}]")
