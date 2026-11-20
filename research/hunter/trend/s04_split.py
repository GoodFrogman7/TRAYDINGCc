"""H3b: the four (trend x break) quadrants, split by year, several horizons."""
import numpy as np, pandas as pd
from lib import *
pd.set_option("display.width", 220)

def quad(L, N, trend_sign, brk, side_out, btc=None, strong=None):
    def sig(s, df, data):
        c = df["close"]
        r = ta.ret(c, L)
        tr = np.sign(r)
        if strong is not None:
            rk = ta.rolling_rank(r.abs(), 4320)
            tr = tr.where(rk >= strong, 0)
        b = (c > ta.donchian_high(df, N)) if brk == "hi" else (c < ta.donchian_low(df, N))
        side = pd.Series(0, index=df.index)
        m = b & (tr == trend_sign)
        if btc is not None:
            bc = data[BTC]["close"]
            m &= (align_btc(np.sign(ta.ret(bc, btc)), df.index) == trend_sign)
        side[m] = side_out
        return side
    return sig

def tab(name, fn, Hs=(24, 48, 72, 168), gap=24):
    rows = []
    for H in Hs:
        ev = collect(fn, H, gap=gap)
        st = stats(ev["r"])
        row = dict(H=H, **st)
        for y in (2022, 2023, 2024):
            sy = stats(ev.loc[ev.index.year == y, "r"])
            row[f"n{y%100}"] = sy["n"]; row[f"m{y%100}"] = sy["mean"]; row[f"med{y%100}"] = sy["med"]
        sm, sa = stats(ev.loc[ev.sym.isin(MAJORS), "r"]), stats(ev.loc[~ev.sym.isin(MAJORS), "r"])
        row["maj"] = sm["mean"]; row["alt"] = sa["mean"]
        rows.append(row)
    print(f"\n== {name}")
    print(pd.DataFrame(rows).to_string(index=False))

if __name__ == "__main__":
    for L in (336,):
        for N in (48, 168):
            tab(f"UP-trend(L={L}) + {N}h-HIGH break -> LONG (breakout continuation)", quad(L, N, 1, "hi", 1))
            tab(f"DOWN-trend(L={L}) + {N}h-LOW break -> SHORT (breakdown continuation)", quad(L, N, -1, "lo", -1))
            tab(f"UP-trend(L={L}) + {N}h-LOW break -> LONG (dip buy)", quad(L, N, 1, "lo", 1))
            tab(f"DOWN-trend(L={L}) + {N}h-HIGH break -> SHORT (rip sell)", quad(L, N, -1, "hi", -1))
    tab("UP-trend(336)+BTC up(336) + 48h-HIGH break -> LONG", quad(336, 48, 1, "hi", 1, btc=336))
    tab("UP-trend(336)+BTC DOWN(336) + 48h-HIGH break -> LONG", lambda s, df, data: quad(336, 48, 1, "hi", 1)(s, df, data).where(align_btc(np.sign(ta.ret(data[BTC]["close"], 336)), df.index) < 0, 0))
    tab("DOWN-trend(336)+BTC down(336) + 48h-HIGH break -> SHORT", quad(336, 48, -1, "hi", -1, btc=336))
