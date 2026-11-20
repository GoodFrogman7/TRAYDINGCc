"""Event studies for the exact rules of the submitted ideas. Signal at close of t, entry at open of t+1, declustered 24 bars per symbol.
Design window only; only bars where the symbol is in the point-in-time top 10."""
from panel import *
from desk.strategies import ta
data, W = build()
P = W["premium"]; tr = W["tradable"]
pm8 = P.rolling(8, min_periods=8).mean()
Z = (pm8 - pm8.rolling(720, min_periods=360).median()) / P.rolling(720, min_periods=360).std()
nb = ((Z <= -2.0) & tr).sum(axis=1)
def cascade(k, z=2.0):
    def f(df, s):
        return ((Z[s].reindex(df.index) <= -z) & (nb.reindex(df.index) >= k) & (pm8[s].reindex(df.index) < 0)).astype(int)
    return f
def solo(df, s):
    return ((Z[s].reindex(df.index) <= -2.0) & (pm8[s].reindex(df.index) <= -0.0005)).astype(int)
def oiwash(df, s):
    d = df["oi"] / df["oi"].shift(24) - 1
    return ((df["close"] < ta.donchian_low(df, 72)) & (d <= -0.15)).astype(int)
def basket(df, s):
    return (nb.reindex(df.index) >= 3).astype(int)
def hot(df, s):
    return ((df["close"] < ta.donchian_low(df, 24)) & (df["premium"].rolling(24, min_periods=24).mean() >= 0.0005)).astype(int)
def spike(df, s):
    return -(df["premium"] >= 0.0040).astype(int)
def pile(df, s):
    c = df["close"]; oi = df["oi"]
    return (((c / c.shift(24) - 1) <= -0.05) & ((oi / oi.shift(24) - 1) >= 0.05) & (df["premium"].rolling(8, min_periods=8).mean() < 0)).astype(int)
def lscap(df, s):
    rk = df["ls_ratio"].rolling(720, min_periods=360).rank(pct=True)
    return ((rk <= 0.10) & ((df["close"] / df["close"].shift(24) - 1) <= -0.03)).astype(int)
def mirror(df, s):
    nr = ((Z >= 2.0) & tr).sum(axis=1)
    return -((Z[s].reindex(df.index) >= 2.0) & (nr.reindex(df.index) >= 2)).astype(int)
print("unconditional fwd 36h mean bps (tradable bars):", round(fwd(W, 36).where(tr).stack().mean() * 1e4, 1),
      "| by year:", {y: round(fwd(W, 36).where(tr)[fwd(W, 36).index.year == y].stack().mean() * 1e4, 1) for y in (2022, 2023, 2024)})
for lab, f, h in (("carry_cascade_discount: own z<=-2 & pm8<0 & breadth>=2, 36h", cascade(2), 36),
                  ("  control breadth==1 only (idiosyncratic discount), 36h", lambda df, s: ((Z[s].reindex(df.index) <= -2.0) & (nb.reindex(df.index) == 1) & (pm8[s].reindex(df.index) < 0)).astype(int), 36),
                  ("  neighbour breadth>=3, 36h", cascade(3), 36),
                  ("carry_deep_discount: own z<=-2 & pm8<=-5bp, 36h", solo, 36),
                  ("carry_oi_washout: close<72h low & OI 24h<=-15%, 36h", oiwash, 36),
                  ("carry_flush_basket: breadth>=3 -> every tradable symbol, 48h", basket, 48),
                  ("carry_hot_dip: close<24h low & pm24>=5bp, 24h", hot, 24),
                  ("carry_premium_spike_short: 1h premium>=40bp, short 8h", spike, 8),
                  ("carry_short_pile_squeeze: ret24<=-5% & OI24>=+5% & pm8<0, 24h", pile, 24),
                  ("carry_retail_capitulation: ls rank30d<=10% & ret24<=-3%, 24h", lscap, 24),
                  ("mirror: own z>=+2 & rich breadth>=2 -> short 36h", mirror, 36)):
    study(collect(data, f, h, gap=24), label=lab)
