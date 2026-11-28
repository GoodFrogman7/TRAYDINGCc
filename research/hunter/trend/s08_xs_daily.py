"""H9 cross-sectional momentum among the month's top-10; H10 daily-scale with-trend impulse; H11 impulse split by liquidations."""
import numpy as np, pandas as pd
from lib import *
from s07_impulse import sigfn
pd.set_option("display.width", 220)

if __name__ == "__main__":
    data = load()
    # ---------- H9: cross-sectional momentum. Rebalance every `H` hours at 00:00 UTC.
    idx = data[BTC].index
    close = pd.DataFrame({s: df["close"] for s, df in data.items()}).reindex(idx)
    opn = pd.DataFrame({s: df["open"] for s, df in data.items()}).reindex(idx)
    trd = pd.DataFrame({s: df["trd"] for s, df in data.items()}).reindex(idx).fillna(False).astype(bool)
    print("H9 cross-sectional momentum: long top-k / short bottom-k of tradable set by L-bar return; signal 23:00 bar close, enter next open")
    for L in (168, 336, 720):
        for H in (72, 168):
            r = close / close.shift(L) - 1
            f = opn.shift(-(1 + H)) / opn.shift(-1) - 1
            rows = []
            for t in idx[(idx.hour == 23)][L // 24 + 1::H // 24]:
                m = trd.loc[t] & r.loc[t].notna() & f.loc[t].notna()
                if m.sum() < 8:
                    continue
                rk = r.loc[t][m].sort_values()
                lo, hi = rk.index[:2], rk.index[-2:]
                rows.append(dict(t=t, long=f.loc[t, hi].mean(), short=-f.loc[t, lo].mean(), mkt=f.loc[t][m].mean()))
            d = pd.DataFrame(rows).set_index("t")
            d["ls"] = (d["long"] + d["short"]) / 2          # per-leg average, signed
            st = lambda x: (round(x.mean() * 1e4, 1), round(x.mean() / x.std() * np.sqrt(len(x)), 2))
            print(f"L={L} H={H} n_rebal={len(d)} per-leg mean bps,t: LS {st(d.ls)} long-mkt {st(d.long - d.mkt)} short+mkt {st(d.short + d.mkt)} | by year LS",
                  {y: round(d.ls[d.index.year == y].mean() * 1e4, 1) for y in (2022, 2023, 2024)})

    # ---------- H10: daily-scale with-trend impulse: 24h return > k x trailing 30d std of 24h returns, volume 24h > 2x 30d mean
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
    print("\nH10 daily-scale with-trend impulse (24h ret > 2 sd, 24h volume > 2x)")
    for H in (72, 168):
        ev = collect(daily_imp(), H, gap=72)
        print(f"H={H}", stats(ev["r"]), "L/S", stats(ev.loc[ev.side == 1, "r"])["mean"], stats(ev.loc[ev.side == -1, "r"])["mean"],
              "years", [(stats(ev.loc[ev.index.year == y, "r"])["n"], stats(ev.loc[ev.index.year == y, "r"])["mean"]) for y in (2022, 2023, 2024)])

    # ---------- H11: hourly with-trend impulse split by liquidation share of the bar's volume
    print("\nH11 with-trend impulse (k2.5 v3) split by liq_vol/volume of the impulse bar, H=72")
    ev = collect(sigfn(), 72, gap=24)
    ls = []
    for s, t in zip(ev.sym, ev.index):
        df = data[s]; ls.append(df.at[t, "liq_vol"] / max(df.at[t, "volume"], 1e-12))
    ev["liq"] = ls
    print("liq share quantiles:", ev.liq.quantile([.25, .5, .75, .9]).round(4).to_dict())
    med = ev.liq.median()
    for lab, m in (("liq share <= median", ev.liq <= med), ("liq share > median", ev.liq > med)):
        e = ev[m]; print(lab, stats(e["r"]), "L/S", stats(e.loc[e.side == 1, "r"])["mean"], stats(e.loc[e.side == -1, "r"])["mean"],
                         "years", [stats(e.loc[e.index.year == y, "r"])["mean"] for y in (2022, 2023, 2024)])
