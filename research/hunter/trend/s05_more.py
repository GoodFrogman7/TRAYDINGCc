"""H4-H8: regime-filtered breakouts, squeeze+trend, crowding (premium) filter, impulse bars, OI-confirmed breaks."""
import numpy as np, pandas as pd
from lib import *
from s04_split import tab, quad
pd.set_option("display.width", 220)

def btc_feat(data, index, fn):
    return align_btc(fn(data[BTC]), index)

# H4: long breakouts in uptrend gated by a SLOW BTC regime (BTC close > its 90-day SMA)
def h4(N=168, slow=2160, side=1):
    def sig(s, df, data):
        base = quad(336, N, side, "hi" if side > 0 else "lo", side)(s, df, data)
        reg = btc_feat(data, df.index, lambda b: np.sign(b["close"] / ta.sma(b["close"], slow) - 1))
        return base.where(reg == side, 0)
    return sig
tab("H4 LONG 168h-high break, coin 14d up, BTC > SMA90d", h4(168, 2160, 1))
tab("H4 SHORT 168h-low break, coin 14d down, BTC < SMA90d", h4(168, 2160, -1))

# H5: squeeze + trend direction
def h5(q=0.2):
    def sig(s, df, data):
        c = df["close"]
        pct = ta.rolling_rank(ta.bb_width(c, 48), 720)
        sq = pct.shift(1).rolling(6).min() <= q
        tr = np.sign(ta.ret(c, 336))
        side = pd.Series(0, index=df.index)
        side[(c > ta.donchian_high(df, 48)) & sq & (tr > 0)] = 1
        side[(c < ta.donchian_low(df, 48)) & sq & (tr < 0)] = -1
        return side
    return sig
tab("H5 squeeze(q=.2) + 48h break in direction of 14d trend (long & short)", h5())
def h5l(s, df, data):
    return h5()(s, df, data).clip(lower=0)
tab("H5 squeeze + 48h-high break in uptrend, LONG only", h5l)

# H6: trend + crowding. Uptrend with LOW premium (shorts paying / spot-led) vs HIGH premium (crowded longs)
def h6(which="uncrowded", L=336):
    def sig(s, df, data):
        c = df["close"]
        tr = np.sign(ta.ret(c, L))
        pm = df["premium"].rolling(24, min_periods=24).mean()
        rk = ta.rolling_rank(pm, 720)
        side = pd.Series(0, index=df.index)
        if which == "uncrowded":
            side[(tr > 0) & (rk <= 0.25)] = 1
            side[(tr < 0) & (rk >= 0.75)] = -1
        else:
            side[(tr > 0) & (rk >= 0.75)] = 1
            side[(tr < 0) & (rk <= 0.25)] = -1
        return side
    return sig
tab("H6 trend(14d) + UNCROWDED premium (long if premium rank<=.25, short if >=.75)", h6("uncrowded"), Hs=(24, 72, 168), gap=72)
tab("H6 trend(14d) + CROWDED premium (control)", h6("crowded"), Hs=(24, 72, 168), gap=72)

# H7: impulse bar: 1h move > k x ATR(24) with volume > 3x its 168h mean, in the direction of the 14d trend / against
def h7(k=2.5, with_trend=True):
    def sig(s, df, data):
        c = df["close"]
        a = ta.atr(df, 24).shift(1)
        mv = (c - df["open"]) / a
        vol = df["volume"] / ta.sma(df["volume"], 168).shift(1)
        tr = np.sign(ta.ret(c, 336).shift(1))
        side = pd.Series(0, index=df.index)
        big = (mv.abs() > k) & (vol > 3)
        d = np.sign(mv)
        m = big & ((d == tr) if with_trend else (d == -tr))
        side[m] = d[m]
        return side
    return sig
tab("H7 impulse bar (>2.5 ATR, vol>3x) WITH 14d trend -> follow", h7(2.5, True), Hs=(6, 24, 72))
tab("H7 impulse bar (>2.5 ATR, vol>3x) AGAINST 14d trend -> follow", h7(2.5, False), Hs=(6, 24, 72))

# H8: OI-confirmed breakout (needs oi, 2023-03+): 48h-high break in uptrend with OI up vs down over 24h
def h8(oi_up=True):
    def sig(s, df, data):
        if df["oi"].notna().sum() < 1000:
            return None
        c = df["close"]
        tr = np.sign(ta.ret(c, 336))
        d_oi = df["oi"] / df["oi"].shift(24) - 1
        side = pd.Series(0, index=df.index)
        m = (c > ta.donchian_high(df, 48)) & (tr > 0) & ((d_oi > 0.03) if oi_up else (d_oi < -0.0))
        side[m] = 1
        return side
    return sig
tab("H8 uptrend 48h-high break with OI +3% in 24h (new longs) -> LONG", h8(True))
tab("H8 uptrend 48h-high break with OI falling (short cover) -> LONG", h8(False))
