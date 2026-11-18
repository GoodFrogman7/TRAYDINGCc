"""D: OI building while price goes sideways = fuel. Then trade the breakout of the range.
Compare breakouts with fuel vs without."""
from lib import *
from desk.strategies import ta
data = load()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
def mk(n, fuel, side, oin=72, oithr=0.15, squeeze=None):
    def f(df, s):
        c = df["close"]; oi = df["oi"]
        doi = (oi / oi.shift(oin) - 1).shift(1)          # OI build measured up to the bar before the break
        rng = ((df["high"].rolling(n).max() - df["low"].rolling(n).min()) / c).shift(1)
        rk = rrank(rng, 720)
        m = (c > ta.donchian_high(df, n)) if side > 0 else (c < ta.donchian_low(df, n))
        m &= doi.notna()
        if fuel == "build": m &= doi >= oithr
        if fuel == "flat": m &= doi.abs() < 0.05
        if fuel == "drop": m &= doi <= -oithr
        if squeeze == "tight": m &= rk <= 0.3
        if squeeze == "wide": m &= rk >= 0.7
        return m.astype(int) * side
    return f
for h in (24, 48):
    print(f"### donchian72 breakout, hold {h}h, by OI 72h change before the break")
    for fuel in (None, "build", "flat", "drop"):
        for sq in (None, "tight"):
            ev = pd.concat([collect(data, mk(72, fuel, 1, squeeze=sq), h, gap=h), collect(data, mk(72, fuel, -1, squeeze=sq), h, gap=h)])
            line(ev, f"don72 break fuel={fuel} range={sq} hold {h}")
