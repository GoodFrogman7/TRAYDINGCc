"""H1: time-series momentum at multi-day horizons. sign(past L-bar return) -> next H bars."""
import numpy as np, pandas as pd
from lib import *

pd.set_option("display.width", 220)
rows = []
for L in (24, 72, 168, 336, 720):
    for H in (24, 72, 168):
        def sig(s, df, data, L=L):
            r = ta.ret(df["close"], L)
            return np.sign(r).fillna(0)
        ev = collect(sig, H, gap=H)
        st = stats(ev["r"])
        yr = {y: stats(ev.loc[ev.index.year == y, "r"])["mean"] for y in (2022, 2023, 2024)}
        lg, sh = stats(ev.loc[ev.side == 1, "r"]), stats(ev.loc[ev.side == -1, "r"])
        rows.append(dict(L=L, H=H, n=st["n"], mean=st["mean"], med=st["med"], hit=st["hit"], t=st["t"], t_day=st["t_day"],
                         y22=yr[2022], y23=yr[2023], y24=yr[2024], long=lg["mean"], short=sh["mean"]))
print(pd.DataFrame(rows).to_string(index=False))
