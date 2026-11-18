"""Path study: how deep does the knife go after the signal (MAE in ATR units), and does waiting for a turn bar help?"""
from lib import *
from desk.strategies import ta
data = load()
def sig_oi(df):
    d = df["oi"] / df["oi"].shift(24) - 1
    return (df["close"] < ta.donchian_low(df, 72)) & (d <= -0.15)
def sig_disc(df):
    pm = df["premium"].rolling(8, min_periods=8).mean()
    med = pm.rolling(720, min_periods=360).median(); sd = df["premium"].rolling(720, min_periods=360).std()
    return ((pm - med) / sd <= -2.5) & (pm <= -0.0005)
def sig_hot(df):
    pm = df["premium"].rolling(24, min_periods=24).mean()
    return (df["close"] < ta.donchian_low(df, 24)) & (pm >= 0.0005)
H = 36
for nm, fn in (("oi_washout", sig_oi), ("discount", sig_disc), ("hot_dip", sig_hot)):
    rows = []
    for s, df in data.items():
        m = decluster((fn(df) & df["tradable"]).fillna(False), 24)
        atr = ta.atr(df, 24)
        o = df["open"].to_numpy(); lo = df["low"].to_numpy(); hi = df["high"].to_numpy(); a = atr.to_numpy()
        for i in np.nonzero(m.to_numpy())[0]:
            if i + 1 + H >= len(df) or not np.isfinite(a[i]): continue
            e = o[i + 1]
            mae = (lo[i + 1:i + 1 + H].min() - e) / a[i]
            mfe = (hi[i + 1:i + 1 + H].max() - e) / a[i]
            tlow = int(np.argmin(lo[i + 1:i + 1 + H]))
            rows.append(dict(time=df.index[i], sym=s, mae=mae, mfe=mfe, tlow=tlow, r=(o[i + 1 + H] / e - 1), atrp=a[i] / e))
    t = pd.DataFrame(rows)
    print(f"== {nm}: n={len(t)} atr%={t.atrp.median()*100:.2f} fwd{H}h mean={t.r.mean()*1e4:.0f}bp  MAE(ATR) q25/50/75={t.mae.quantile([.25,.5,.75]).round(2).tolist()} MFE q50={t.mfe.median():.2f}")
    for k in (2, 3, 4, 5):
        hitk = t.mae <= -k
        print(f"   stop {k} ATR: hit {hitk.mean():.2f}; mean fwd of those hit (if held)={t.r[hitk].mean()*1e4:.0f}bp; not hit={t.r[~hitk].mean()*1e4:.0f}bp")
    print("   bars to the low within hold: q25/50/75 =", t.tlow.quantile([.25, .5, .75]).tolist())
