"""How often would the off-market print filter (trade open/close far from the venue's mark and spot
closes) and the inconsistent-bar checks flag a bar of the research data? Read-only."""
import numpy as np
import pandas as pd
from desk.data import store

LIM = 0.25
tot = 0
for s in store.symbols():
    df = pd.read_parquet(store.H1 / f"{s}.parquet")
    real = ~df["bar_missing"].astype(bool)
    o, h, lo, c = (df[x].to_numpy("float64") for x in ("open", "high", "low", "close"))
    m, sp = df["mark_close"].to_numpy("float64"), df["spot_close"].to_numpy("float64")
    incons = real & ((h < np.maximum(o, c)) | (lo > np.minimum(o, c)))
    with np.errstate(invalid="ignore", divide="ignore"):
        dm, ds = np.abs(c / m - 1), np.abs(c / sp - 1)
        has = np.isfinite(dm) | np.isfinite(ds)
        near = (dm <= LIM) | (ds <= LIM)
        offc = real & has & ~near
        pm, ps = np.r_[np.nan, m[:-1]], np.r_[np.nan, sp[:-1]]
        devs = [np.abs(o / x - 1) for x in (pm, ps, m, sp)]
        has_o = np.any([np.isfinite(d) for d in devs], axis=0)
        near_o = np.any([d <= LIM for d in devs], axis=0)
        offo = real & has_o & ~near_o
        noref = real & ~has
    tot += len(df)
    if incons.sum() or offc.sum() or offo.sum():
        print(s, "rows", len(df), "inconsistent", int(incons.sum()), "off close", int(offc.sum()), "off open", int(offo.sum()),
              "no ref", int(noref.sum()))
        for t in df.index[offc | offo | incons][:5]:
            print("   ", t, df.loc[t, ["open", "high", "low", "close", "mark_close", "spot_close"]].to_dict())
print("total rows", tot)
