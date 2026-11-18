"""(a) liquidation-cascade signature: perp discount AND OI flush together vs each alone (2023-03 onward so all rows share a window)."""
from lib import *
from desk.strategies import ta
data = load()
def mk(kind):
    def f(df, s):
        pm = df["premium"].rolling(8, min_periods=8).mean()
        med = pm.rolling(720, min_periods=360).median(); sd = df["premium"].rolling(720, min_periods=360).std()
        z = (pm - med) / sd
        oi = df["oi"]; d = oi / oi.shift(24) - 1
        disc = (z <= -2.0)
        flush = (d <= -0.10)
        has = d.notna()
        if kind == "disc_only": m = disc & ~flush & has
        if kind == "flush_only": m = flush & ~disc & has & (df["close"] < ta.donchian_low(df, 72))
        if kind == "both": m = disc & flush
        if kind == "disc_any": m = disc & has
        return m.astype(int)
    return f
for h in (24, 48):
    for kind in ("disc_any", "disc_only", "flush_only", "both"):
        line(collect(data, mk(kind), h, gap=24), f"{kind} long {h}h (z<=-2 / OI24h<=-10%)")
