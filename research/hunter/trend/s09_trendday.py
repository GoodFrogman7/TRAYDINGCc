"""H10 detail (trend day) + H12 quiet/efficient trend continuation."""
import numpy as np, pandas as pd
from lib import *
from s06_sides import sidetab
pd.set_option("display.width", 220)

def daily_imp(k=2.0, vmult=2.0, L=336):
    def sig(s, df, data):
        c = df["close"]
        r24 = c / c.shift(24) - 1
        sd = r24.rolling(720, min_periods=360).std().shift(24)
        v24 = df["volume"].rolling(24).sum()
        vr = v24 / v24.shift(24).rolling(720, min_periods=360).mean()
        tr = np.sign(ta.ret(c, L).shift(24))
        big = (r24.abs() > k * sd) & (vr > vmult) & (np.sign(r24) == tr)
        side = pd.Series(0, index=df.index); side[big] = tr[big]
        return side
    return sig

def against(k=2.0, vmult=2.0, L=336):
    def sig(s, df, data):
        c = df["close"]
        r24 = c / c.shift(24) - 1
        sd = r24.rolling(720, min_periods=360).std().shift(24)
        v24 = df["volume"].rolling(24).sum()
        vr = v24 / v24.shift(24).rolling(720, min_periods=360).mean()
        tr = np.sign(ta.ret(c, L).shift(24))
        big = (r24.abs() > k * sd) & (vr > vmult) & (np.sign(r24) == -tr)
        side = pd.Series(0, index=df.index); side[big] = np.sign(r24)[big]
        return side
    return sig

def quiet(L=336, q=0.8):
    def sig(s, df, data):
        c = df["close"]
        er = ta.efficiency_ratio(c, L)
        rk = ta.rolling_rank(er, 4320)
        tr = np.sign(ta.ret(c, L))
        side = pd.Series(0, index=df.index)
        m = rk >= q
        side[m] = tr[m]
        return side
    return sig

if __name__ == "__main__":
    for H in (24, 72, 168):
        sidetab("TREND DAY k2 v2 L336", daily_imp(), H, gap=72)
    sidetab("TREND DAY delay+1", daily_imp(), 168, gap=72, delay=1)
    sidetab("TREND DAY k1.5", daily_imp(k=1.5), 168, gap=72)
    sidetab("TREND DAY k2.5", daily_imp(k=2.5), 168, gap=72)
    sidetab("TREND DAY v1.5", daily_imp(vmult=1.5), 168, gap=72)
    sidetab("CONTROL: 2-sigma day on 2x volume AGAINST the 14d trend -> follow the day", against(), 168, gap=72)
    ev = collect(daily_imp(), 168, gap=72)
    r = ev["r"]
    print("\nTREND DAY 168h: quantiles bps", (r.quantile([.05, .25, .5, .75, .95]) * 1e4).round(0).to_dict(),
          "| share of PnL from top 5%:", round(r[r >= r.quantile(.95)].sum() / r.sum(), 2),
          "| distinct days:", ev.index.floor("D").nunique(), "| majors/alts:", stats(ev.loc[ev.sym.isin(MAJORS), "r"])["mean"], stats(ev.loc[~ev.sym.isin(MAJORS), "r"])["mean"])
    print("per symbol:", ev.groupby("sym")["r"].agg(["size", "mean"]).assign(mean=lambda d: (d["mean"] * 1e4).round(0)).sort_values("size", ascending=False).head(12).T.to_string())
    for H in (72, 168):
        sidetab("QUIET TREND: ER(336) in top 20% of trailing 180d -> follow", quiet(), H, gap=168)
