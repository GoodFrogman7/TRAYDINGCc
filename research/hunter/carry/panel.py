"""Wide panels (time x symbol) for bucket studies. Design window only."""
from lib import *

def build():
    data = load()
    idx = pd.date_range(min(d.index[0] for d in data.values()), max(d.index[-1] for d in data.values()), freq="h")
    W = {}
    for c in ["open", "high", "low", "close", "premium", "funding", "oi", "ls_ratio", "mark_close", "spot_close", "volume", "liq_vol", "buy_vol", "sell_vol", "tradable"]:
        W[c] = pd.DataFrame({s: d[c].reindex(idx) for s, d in data.items()})
    W["tradable"] = W["tradable"].fillna(False).astype(bool)
    return data, W

def fwd(W, h, delay=0):
    o = W["open"]
    return o.shift(-(1 + delay + h)) / o.shift(-(1 + delay)) - 1.0

def bucket_table(feat: pd.DataFrame, W, hs=(4, 12, 24, 48, 72), qs=(0, .02, .1, .3, .7, .9, .98, 1), label="", demean=False, step=None):
    """feat should already be a trailing rank in [0,1] (or pass raw and qs as absolute edges)."""
    tr = W["tradable"]
    out = []
    for h in hs:
        f = fwd(W, h)
        if demean:
            f = f.sub(f.where(tr).mean(axis=1), axis=0)
        st = step or 1
        x = feat.where(tr).iloc[::st].stack()
        y = f.where(tr).iloc[::st].stack()
        df = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
        df["b"] = pd.cut(df["x"], list(qs), include_lowest=True)
        g = df.groupby("b", observed=True)["y"]
        row = (g.mean() * 1e4).round(1).astype(str) + " (" + g.count().astype(str) + ")"
        out.append(row.rename(f"h{h}"))
    t = pd.concat(out, axis=1)
    print(f"--- {label} {'[xs-demeaned]' if demean else '[raw]'}")
    print(t.to_string())
