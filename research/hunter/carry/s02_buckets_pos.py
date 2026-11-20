from panel import *
pd.set_option("display.width", 250)
data, W = build()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
L = W["ls_ratio"]; OI = W["oi"]; C = W["close"]
print("ls_ratio describe"); print(L.where(W["tradable"]).stack().describe())
# ls level (absolute)
bucket_table(L, W, qs=(0, .5, .6, .7, .75, .8, .85, .9, 1.0), label="ls_ratio absolute level")
bucket_table(L, W, qs=(0, .5, .6, .7, .75, .8, .85, .9, 1.0), label="ls_ratio absolute level", demean=True)
bucket_table(rrank(L, 720), W, label="ls_ratio rank30d")
bucket_table(rrank(L, 720), W, label="ls_ratio rank30d", demean=True)
dL = L - L.shift(24)
bucket_table(rrank(dL, 720), W, label="ls_ratio 24h change rank30d")
bucket_table(rrank(dL, 720), W, label="ls_ratio 24h change rank30d", demean=True)
# OI change
for n in (24, 72):
    dOI = OI / OI.shift(n) - 1
    bucket_table(rrank(dOI, 720), W, label=f"OI {n}h pct change rank30d")
    bucket_table(rrank(dOI, 720), W, label=f"OI {n}h pct change rank30d", demean=True)
# OI change 4h (flush)
dOI4 = OI / OI.shift(4) - 1
bucket_table(rrank(dOI4, 720), W, label="OI 4h pct change rank30d")
# funding column (level, estimate) cum 24h
F = W["funding"].rolling(24, min_periods=24).sum()
bucket_table(F * 1e4, W, qs=(-1000, -10, -3, 0, 3, 6, 10, 20, 1000), label="funding 24h sum in bps (abs)")
