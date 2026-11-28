from lib import *
from desk.strategies import ta
data = load()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
def wash(dn, oin, thr):
    def f(df, s):
        oi = df["oi"]; d = oi / oi.shift(oin) - 1
        lo = ta.donchian_low(df, dn)
        m = (df["close"] < lo) & d.notna()
        if thr is None: pass
        elif thr > 0: m &= d >= thr
        else: m &= d <= thr
        return m.astype(int)
    return f
print("### OI washout: new N-bar low AND OI change over M bars <= thr -> long 24h (control = no OI filter / OI not down)")
for dn, oin, thr in ((72, 24, None), (72, 24, -0.10), (72, 24, -0.15), (72, 24, -0.20), (72, 24, 0.0001), (48, 24, -0.15), (24, 24, -0.15), (72, 72, -0.15), (72, 8, -0.10)):
    line(collect(data, wash(dn, oin, thr), 24, gap=24), f"don{dn} low & OI {oin}h chg {thr} long 24h")
print("### same, 48h hold")
for dn, oin, thr in ((72, 24, -0.15), (48, 24, -0.15)):
    line(collect(data, wash(dn, oin, thr), 48, gap=48), f"don{dn} low & OI {oin}h chg {thr} long 48h")

def flip_dn_long(ma):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        m = (pm < 0) & (pm.shift(1) >= 0) & (pm.shift(1).rolling(ma).min() >= 0)
        return m.astype(int)
    return f
print("### first-discount flip robustness across windows (long 24h)")
for ma in (36, 48, 60, 72, 96, 120):
    line(collect(data, flip_dn_long(ma), 24, gap=24), f"prem_ma{ma} flips DOWN after {ma}h>=0 -> LONG 24h")

def ls_cap(q, pthr, n=24):
    def f(df, s):
        ls = df["ls_ratio"]
        m = (rrank(ls, 720) <= q) & ((df["close"] / df["close"].shift(n) - 1) <= -pthr)
        return m.astype(int)
    return f
print("### retail capitulation: ls_ratio trailing-30d rank <= q and price down >= pthr over 24h -> long 24h; control = price down only")
for q, pthr in ((1.01, 0.03), (0.05, 0.03), (0.10, 0.03), (0.05, 0.05), (0.02, 0.03)):
    line(collect(data, ls_cap(q, pthr), 24, gap=24), f"ls rank<={q} & 24h ret<=-{pthr}")
