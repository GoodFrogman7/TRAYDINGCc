"""F: premium regime as a trend filter. (1) premium sign flip of the slow average. (2) breakout conditioned on premium state.
   G: funding-carry short when crowded longs stall."""
from lib import *
from desk.strategies import ta
data = load()
def flip(ma, side):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        if side > 0:
            m = (pm > 0) & (pm.shift(1) <= 0) & (pm.shift(1).rolling(ma).max() <= 0)   # first positive print after >= ma bars negative
        else:
            m = (pm < 0) & (pm.shift(1) >= 0) & (pm.shift(1).rolling(ma).min() >= 0)
        return m.astype(int) * side
    return f
print("### F1: slow premium average flips sign after being one-sided for >= ma bars; trade in the direction of the flip")
for ma in (24, 72):
    for h in (24, 72):
        ev = pd.concat([collect(data, flip(ma, 1), h, gap=h), collect(data, flip(ma, -1), h, gap=h)])
        line(ev, f"prem_ma{ma} flip, hold {h}h")

def brk(n, cond, side):
    def f(df, s):
        c = df["close"]
        pm = df["premium"].rolling(24, min_periods=24).mean()
        if side > 0:
            m = (c > ta.donchian_high(df, n)) 
        else:
            m = (c < ta.donchian_low(df, n))
        if cond == "prem_with": m &= (pm * side > 0.0002)       # premium agrees with the break (crowd already positioned)
        if cond == "prem_against": m &= (pm * side < -0.0002)   # premium disagrees (crowd offside)
        if cond == "prem_neutral": m &= (pm.abs() <= 0.0002)
        return m.astype(int) * side
    return f
print("### F2: 96h Donchian breakout conditioned on 24h premium state")
for h in (24, 72):
    for cond in (None, "prem_with", "prem_neutral", "prem_against"):
        ev = pd.concat([collect(data, brk(96, cond, 1), h, gap=h), collect(data, brk(96, cond, -1), h, gap=h)])
        line(ev, f"donchian96 break [{cond}] hold {h}h")

def carry_short(fthr, cond):
    def f(df, s):
        f24 = df["premium"].rolling(24, min_periods=24).mean() * 1e4
        c = df["close"]
        m = f24 >= fthr
        if cond == "stall": m &= c < c.rolling(24).mean()
        if cond == "break": m &= c < ta.donchian_low(df, 24)
        return -m.astype(int)
    return f
print("### G: 24h mean premium >= X bps and price rolls over -> short")
for h in (24, 48):
    for thr in (8, 15):
        for cond in (None, "stall", "break"):
            line(collect(data, carry_short(thr, cond), h, gap=h), f"prem_ma24>={thr}bp [{cond}] short {h}h")
