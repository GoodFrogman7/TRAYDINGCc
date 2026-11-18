"""Truncation test on the research copies: intents at T from data cut at T must equal intents from full design history."""
import numpy as np, pandas as pd
from lib import load
from strats import Impulse
from strats3 import TrendDay, XSMom
from strats4 import QuietTrend
from s06_sides import sidetab
from s09_trendday import quiet

data = {s: df.drop(columns=["trd"]) for s, df in load().items()}
syms = ["PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD", "PF_XRPUSD", "PF_DOGEUSD", "PF_ADAUSD", "PF_LINKUSD", "PF_LTCUSD", "PF_AVAXUSD", "PF_MATICUSD", "PF_PEPEUSD", "PF_WIFUSD"]
sub = {s: data[s] for s in syms}
for S, p in ((TrendDay(), {}), (Impulse(), {"mode": 1}), (QuietTrend(), {}), (XSMom(), {})):
    P = {**S.params, **p}
    full = S.intents(sub, P)
    bad = n = 0
    for T in pd.to_datetime(["2023-03-05 23:00", "2023-11-12 23:00", "2024-03-10 23:00", "2024-08-04 23:00", "2024-11-17 23:00"], utc=True):
        cut = {s: df[df.index <= T] for s, df in sub.items() if (df.index <= T).any()}
        part = S.intents(cut, P)
        for s in part:
            a, b = part[s].iloc[-200:], full[s].loc[part[s].index[-200:]]
            for col in ("side", "limit", "stop", "exit"):
                x, y = a[col].to_numpy(dtype=float), b[col].to_numpy(dtype=float)
                sel = a["side"].to_numpy() != 0 if col != "side" else np.ones(len(a), bool)
                bad += int((~np.isclose(x[sel], y[sel], equal_nan=True)).sum()); n += int(sel.sum())
    print(S.name, "values checked", n, "mismatches", bad)
sidetab("QUIET TREND long/short delay+1", quiet(), 168, gap=168, delay=1)
