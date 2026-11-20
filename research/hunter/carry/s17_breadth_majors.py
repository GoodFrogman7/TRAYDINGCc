"""(1) Market-wide discount breadth -> long majors / long everything. (2) BTC/ETH own discount. (3) shorts piling into lows.
Design window only. Breadth is computed over the point-in-time tradable set at each bar."""
from panel import *
from desk.strategies import ta
data, W = build()
P = W["premium"]; tr = W["tradable"]
pm = P.rolling(8, min_periods=8).mean()
med = pm.rolling(720, min_periods=360).median(); sd = P.rolling(720, min_periods=360).std()
Z = (pm - med) / sd
def mk_breadth(zthr, k, who):
    nb = ((Z <= -zthr) & tr).sum(axis=1)
    nt = tr.sum(axis=1)
    on = (nb >= k) & (nt >= 8)
    def f(df, s):
        if who == "maj" and s not in MAJORS: return None
        if who == "alts" and s in MAJORS: return None
        return on.reindex(df.index).fillna(False).astype(int)
    return f, on
print("### breadth of perp discount: >=k of the tradable set with prem_ma8 z<=-zthr; first in 24h; long")
for zthr, k in ((2.0, 3), (2.0, 5), (1.5, 5), (2.5, 3)):
    for who in ("maj", "alts"):
        for h in (24, 48):
            f, on = mk_breadth(zthr, k, who)
            line(collect(data, f, h, gap=24), f"breadth z<=-{zthr} k>={k} -> long {who} {h}h")
print("### control: own-symbol z<=-2 when breadth <=1 (idiosyncratic discount) vs breadth>=3")
nb2 = ((Z <= -2.0) & tr).sum(axis=1)
def own(lo, hi):
    def f(df, s):
        z = Z[s].reindex(df.index); b = nb2.reindex(df.index)
        return ((z <= -2.0) & (b >= lo) & (b <= hi)).astype(int)
    return f
for lo, hi in ((1, 1), (2, 2), (3, 99)):
    line(collect(data, own(lo, hi), 24, gap=24), f"own z<=-2 & breadth in [{lo},{hi}] long 24h")
print("### BTC/ETH own absolute discount (prem_ma8 <= thr bps) long")
def majabs(thr):
    def f(df, s):
        if s not in MAJORS: return None
        return (df["premium"].rolling(8, min_periods=8).mean() * 1e4 <= thr).astype(int)
    return f
for thr in (-4, -6, -8):
    for h in (24, 48):
        line(collect(data, majabs(thr), h, gap=24), f"majors prem_ma8<={thr}bp long {h}h")
print("### shorts piling into the low: price <= -5%/24h, OI up >= x/24h, prem_ma8<0 -> long (squeeze) ; mirror with prem>0")
def pile(oithr, sign):
    def f(df, s):
        c = df["close"]; oi = df["oi"]; p8 = df["premium"].rolling(8, min_periods=8).mean()
        m = ((c / c.shift(24) - 1) <= -0.05) & ((oi / oi.shift(24) - 1) >= oithr)
        m &= (p8 < 0) if sign < 0 else (p8 > 0)
        return m.astype(int)
    return f
for oithr in (0.05, 0.10):
    for sign in (-1, 1):
        line(collect(data, pile(oithr, sign), 24, gap=24), f"price<=-5% & OI>=+{oithr} & prem {'<0' if sign<0 else '>0'} long 24h")
