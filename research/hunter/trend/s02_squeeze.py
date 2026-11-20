"""H2: breakout after a tight squeeze. Squeeze = BB width (n bars) in the bottom q of its trailing 720-bar
distribution within the last `rec` bars; trigger = close beyond the prior N-bar high/low."""
import numpy as np, pandas as pd
from lib import *
pd.set_option("display.width", 220)

def mk(bb_n=48, q=0.2, N=48, rec=6, squeeze=True, btc=False):
    def sig(s, df, data):
        c = df["close"]
        w = ta.bb_width(c, bb_n)
        pct = ta.rolling_rank(w, 720)
        sq = (pct.shift(1).rolling(rec).min() <= q) if squeeze else pd.Series(True, index=df.index)
        up = c > ta.donchian_high(df, N)
        dn = c < ta.donchian_low(df, N)
        side = pd.Series(0, index=df.index)
        side[up & sq] = 1
        side[dn & sq] = -1
        if btc:
            b = data[BTC]["close"]
            bt = align_btc(np.sign(b / ta.sma(b, 168) - 1), df.index)
            side = side.where(np.sign(side) == bt, 0)
        return side
    return sig

for name, kw in [("no-squeeze N=48", dict(squeeze=False)),
                 ("squeeze q=.2 bb48 N=48", dict()),
                 ("squeeze q=.1 bb48 N=48", dict(q=0.1)),
                 ("squeeze q=.2 bb24 N=24", dict(bb_n=24, N=24)),
                 ("squeeze q=.2 bb96 N=96", dict(bb_n=96, N=96)),
                 ("squeeze q=.2 bb48 N=48 +BTC agree", dict(btc=True)),
                 ]:
    for H in (24, 72):
        ev = collect(mk(**kw), H, gap=24)
        print(f"\n== {name}  H={H}")
        print(report(ev).to_string())
    evd = collect(mk(**kw), 24, delay=1, gap=24)
    print("delay+1 H=24:", stats(evd["r"]))
