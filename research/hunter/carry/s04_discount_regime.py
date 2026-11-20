"""A: does a trend/regime filter rescue the 2022 failure of the discount long?"""
from lib import *
data = load()
def rrank(x, n): return x.rolling(n, min_periods=n // 2).rank(pct=True)
btc = data["PF_XBTUSD"]["close"]
btc_up = (btc > btc.rolling(720).mean())
H = 24
def mk(cond):
    def f(df, s):
        pm = df["premium"].rolling(8, min_periods=8).mean()
        m = rrank(pm, 720) <= 0.02
        c = df["close"]
        if cond == "own_up": m &= c > c.rolling(720).mean()
        if cond == "own_dn": m &= c <= c.rolling(720).mean()
        if cond == "btc_up": m &= btc_up.reindex(df.index).fillna(False)
        if cond == "btc_dn": m &= ~btc_up.reindex(df.index).fillna(True)
        if cond == "own_up168": m &= c > c.rolling(168).mean()
        if cond == "own_dn168": m &= c <= c.rolling(168).mean()
        if cond == "drop24": m &= (c / c.shift(24) - 1) < -0.03
        if cond == "nodrop24": m &= (c / c.shift(24) - 1) >= -0.03
        if cond == "abs10": m &= pm < -0.0010
        if cond == "abs20": m &= pm < -0.0020
        return m.astype(int)
    return f
for cond in ("all", "own_up", "own_dn", "btc_up", "btc_dn", "own_up168", "own_dn168", "drop24", "nodrop24", "abs10", "abs20"):
    line(collect(data, mk(cond), H, gap=H), f"prem_ma8 rank<=2% long 24h [{cond}]")
# what do premium levels look like at events
rows = []
for s, df in data.items():
    pm = df["premium"].rolling(8, min_periods=8).mean()
    m = (rrank(pm, 720) <= 0.02) & df["tradable"]
    rows.append(pm[m])
x = pd.concat(rows) * 1e4
print("premium ma8 level at events (bps):", x.describe().round(1).to_dict())
