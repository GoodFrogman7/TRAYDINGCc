"""Side x year decomposition for the survivors so far (is it just bull beta?)."""
import numpy as np, pandas as pd
from lib import *
from s04_split import quad
from s05_more import h7
pd.set_option("display.width", 220)

def sidetab(name, fn, H, gap=24, delay=0):
    ev = collect(fn, H, gap=gap, delay=delay)
    rows = []
    for sd, lab in ((1, "long"), (-1, "short")):
        e = ev[ev.side == sd]
        row = dict(side=lab, **stats(e["r"]))
        for y in (2022, 2023, 2024):
            sy = stats(e.loc[e.index.year == y, "r"])
            row[f"n{y%100}"] = sy["n"]; row[f"m{y%100}"] = sy["mean"]; row[f"med{y%100}"] = sy["med"]
        rows.append(row)
    print(f"\n== {name}  H={H} delay={delay}")
    print(pd.DataFrame(rows).to_string(index=False))
    return ev

def trend_dir_impulse(k=2.5, v=3.0, L=336, mode="both"):
    """Enter in the direction of the 14d trend after an impulse bar (either direction)."""
    def sig(s, df, data):
        c = df["close"]
        a = ta.atr(df, 24).shift(1)
        mv = (c - df["open"]) / a
        vol = df["volume"] / ta.sma(df["volume"], 168).shift(1)
        tr = np.sign(ta.ret(c, L).shift(1))
        big = (mv.abs() > k) & (vol > v)
        d = np.sign(mv)
        side = pd.Series(0, index=df.index)
        if mode in ("both", "with"):
            m = big & (d == tr); side[m] = tr[m]
        if mode in ("both", "against"):
            m = big & (d == -tr); side[m] = tr[m]
        return side
    return sig

if __name__ == "__main__":
    for H in (24, 72):
        sidetab("impulse WITH trend -> follow", trend_dir_impulse(mode="with"), H)
        sidetab("impulse AGAINST trend -> fade (enter with trend)", trend_dir_impulse(mode="against"), H)
    sidetab("impulse AGAINST trend -> fade", trend_dir_impulse(mode="against"), 72, delay=1)
    sidetab("impulse WITH trend -> follow", trend_dir_impulse(mode="with"), 72, delay=1)
    # robustness: 2 nearby settings
    sidetab("impulse k=2.0 v=2.5 both", trend_dir_impulse(2.0, 2.5), 72)
    sidetab("impulse k=3.0 v=3 both", trend_dir_impulse(3.0, 3.0), 72)
    sidetab("impulse k=2.5 v=3 L=168 both", trend_dir_impulse(2.5, 3.0, L=168), 72)
    sidetab("impulse k=2.5 v=3 L=720 both", trend_dir_impulse(2.5, 3.0, L=720), 72)
    # pullback with coin + BTC trend agreement
    def pb(N=48, L=336):
        def sig(s, df, data):
            a = quad(L, N, 1, "lo", 1, btc=L)(s, df, data)
            b = quad(L, N, -1, "hi", -1, btc=L)(s, df, data)
            return a + b
        return sig
    for H in (12, 24, 36):
        sidetab("pullback 48h extreme, coin+BTC 14d trend agree", pb(), H)
    sidetab("pullback 48h extreme, coin+BTC agree", pb(), 24, delay=1)
    sidetab("pullback 24h extreme, coin+BTC agree", pb(N=24), 24)
    sidetab("pullback 72h extreme, coin+BTC agree", pb(N=72), 24)
    sidetab("pullback 48h extreme, L=168 coin+BTC agree", pb(L=168), 24)
    sidetab("pullback 48h extreme, L=720 coin+BTC agree", pb(L=720), 24)
