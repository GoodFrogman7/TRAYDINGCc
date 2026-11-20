"""H3: pullback inside a trend. Trend = sign of L-bar return (and optional strength filter);
trigger = close through the prior N-bar low (uptrend -> buy) / high (downtrend -> sell)."""
import numpy as np, pandas as pd
from lib import *
pd.set_option("display.width", 220)

def mk(L=336, N=48, mode="with", strong=None, btc=None):
    def sig(s, df, data):
        c = df["close"]
        r = ta.ret(c, L)
        tr = np.sign(r)
        if strong is not None:  # |r| in the top (1-strong) of its own trailing-180d distribution
            rk = ta.rolling_rank(r.abs(), 4320)
            tr = tr.where(rk >= strong, 0)
        lo = c < ta.donchian_low(df, N)
        hi = c > ta.donchian_high(df, N)
        side = pd.Series(0, index=df.index)
        if mode == "with":       # buy dips in uptrends, sell rips in downtrends
            side[lo & (tr > 0)] = 1
            side[hi & (tr < 0)] = -1
        elif mode == "against":  # buy dips in downtrends, sell rips in uptrends (pure fade, control)
            side[lo & (tr < 0)] = 1
            side[hi & (tr > 0)] = -1
        if btc is not None:
            b = data[BTC]["close"]
            bt = align_btc(np.sign(ta.ret(b, btc)), df.index)
            side = side.where(np.sign(side) == bt, 0)
        return side
    return sig

for name, kw in [("WITH trend L=336 N=48", dict()),
                 ("AGAINST trend (control) L=336 N=48", dict(mode="against")),
                 ("WITH trend L=336 N=24", dict(N=24)),
                 ("WITH trend L=720 N=48", dict(L=720)),
                 ("WITH trend L=168 N=48", dict(L=168)),
                 ("WITH strong trend (top 50%) L=336 N=48", dict(strong=0.5)),
                 ("WITH trend L=336 N=48 + BTC 336 agree", dict(btc=336)),
                 ]:
    print(f"\n== {name}")
    for H in (24, 48, 72):
        ev = collect(mk(**kw), H, gap=24)
        print(f"-- H={H}")
        print(report(ev).to_string())
    evd = collect(mk(**kw), 48, delay=1, gap=24)
    print("delay+1 H=48:", stats(evd["r"]))
