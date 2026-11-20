from panel import *
pd.set_option("display.width", 250)
data, W = build()
P = W["premium"]
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
feats = {}
for n in (1, 8, 24, 72):
    pm = P.rolling(n, min_periods=n).mean()
    feats[f"prem_ma{n}_rank30d"] = rrank(pm, 720)
# baseline unconditional
for h in (4, 12, 24, 48, 72):
    f = fwd(W, h).where(W["tradable"])
    print("uncond h", h, round(f.stack().mean() * 1e4, 1))
for k, v in feats.items():
    bucket_table(v, W, label=k)
    bucket_table(v, W, label=k, demean=True)
