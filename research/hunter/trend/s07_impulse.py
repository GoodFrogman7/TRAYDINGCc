"""H7 deep-dive: with-trend impulse continuation. Breadth (how many coins fire in the same hour), BTC bar, horizon."""
import numpy as np, pandas as pd
from lib import *
pd.set_option("display.width", 220)

def sigfn(k=2.5, v=3.0, L=336):
    def sig(s, df, data):
        c = df["close"]
        a = ta.atr(df, 24).shift(1)
        mv = (c - df["open"]) / a
        vol = df["volume"] / ta.sma(df["volume"], 168).shift(1)
        tr = np.sign(ta.ret(c, L).shift(1))
        big = (mv.abs() > k) & (vol > v) & (np.sign(mv) == tr)
        side = pd.Series(0, index=df.index); side[big] = tr[big]
        return side
    return sig

if __name__ == "__main__":
    data = load()
    for H in (24, 48, 72, 120, 168):
        ev = collect(sigfn(), H, gap=24)
        print(f"H={H}", stats(ev["r"]), "| long", stats(ev.loc[ev.side == 1, "r"])["mean"], "short", stats(ev.loc[ev.side == -1, "r"])["mean"],
              "| by year", [stats(ev.loc[ev.index.year == y, "r"])["mean"] for y in (2022, 2023, 2024)])
    ev = collect(sigfn(), 72, gap=24)
    # breadth: number of tradable symbols firing in the same hour
    ev["breadth"] = ev.groupby(level=0)["r"].transform("size")
    b = data[BTC]
    bmv = ((b["close"] - b["open"]) / ta.atr(b, 24).shift(1)).abs()
    ev["btc_mv"] = bmv.reindex(ev.index).to_numpy()
    print("\nby breadth (coins firing the same hour), H=72")
    for lab, m in (("1", ev.breadth == 1), ("2-3", ev.breadth.between(2, 3)), ("4+", ev.breadth >= 4)):
        e = ev[m]; print(lab, stats(e["r"]), "years", [stats(e.loc[e.index.year == y, "r"])["mean"] for y in (2022, 2023, 2024)])
    print("\nby BTC same-bar |move| in ATRs (non-BTC symbols), H=72")
    e0 = ev[ev.sym != BTC]
    for lab, m in (("btc<1", e0.btc_mv < 1), ("btc 1-2.5", e0.btc_mv.between(1, 2.5)), ("btc>2.5", e0.btc_mv > 2.5)):
        e = e0[m]; print(lab, stats(e["r"]), "L/S", stats(e.loc[e.side == 1, "r"])["mean"], stats(e.loc[e.side == -1, "r"])["mean"],
                         "years", [stats(e.loc[e.index.year == y, "r"])["mean"] for y in (2022, 2023, 2024)])
    print("\nevents per year / distinct days:", ev.groupby(ev.index.year).size().to_dict(), ev.index.floor("D").nunique())
    print("per symbol:", ev.groupby("sym")["r"].agg(["size", "mean"]).assign(mean=lambda d: (d["mean"] * 1e4).round(0)).sort_values("size", ascending=False).head(14).to_string())
    # winners vs losers
    r = ev["r"]
    print("\nquantiles of 72h signed return (bps):", (r.quantile([.05, .25, .5, .75, .95]) * 1e4).round(0).to_dict())
    print("share of total PnL from top 5% of events:", round(r[r >= r.quantile(.95)].sum() / r.sum(), 2))
    # same test without the volume condition / without the trend condition (controls)
    def novol(s, df, data):
        c = df["close"]; a = ta.atr(df, 24).shift(1); mv = (c - df["open"]) / a
        tr = np.sign(ta.ret(c, 336).shift(1)); big = (mv.abs() > 2.5) & (np.sign(mv) == tr)
        side = pd.Series(0, index=df.index); side[big] = tr[big]; return side
    ev2 = collect(novol, 72, gap=24); print("\ncontrol: no volume filter H=72", stats(ev2["r"]), [stats(ev2.loc[ev2.index.year == y, "r"])["mean"] for y in (2022, 2023, 2024)])
