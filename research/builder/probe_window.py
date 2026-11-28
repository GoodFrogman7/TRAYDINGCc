"""Scratch check (offline): intents on a 3000-bar window of the bot's symbol subset vs the full research history.
Run from the repo root: PYTHONPATH=. python research/builder/probe_window.py"""
import numpy as np
import pandas as pd

from desk.data import store
from desk.strategies.ref_donchian import STRATEGY

full = store.load_all()
end = max(df.index[-1] for df in full.values())
start = end - pd.Timedelta(hours=2999)
months = sorted({m for m in pd.date_range(start, end, freq="h").strftime("%Y-%m")})
uni = store.universe()
subset = sorted({s for m in months for s in uni.get(m, [])} | {"PF_XBTUSD", "PF_ETHUSD"})
print("window months", months, "| symbols needed:", len(subset), "of", len(full), "in the dataset")
win = {s: full[s][full[s].index >= start] for s in subset if s in full}
a = STRATEGY.intents(win, dict(STRATEGY.params))
b = STRATEGY.intents(full, dict(STRATEGY.params))
worst = 0.0
for s in subset:
    x, y = a[s].iloc[-2000:], b[s].reindex(a[s].index).iloc[-2000:]
    assert (x["side"].to_numpy() == y["side"].to_numpy()).all() and (x["exit"].to_numpy() == y["exit"].to_numpy()).all(), s
    for c in ("limit", "stop", "tp", "trail"):
        u, v = x[c].to_numpy(dtype="float64"), y[c].to_numpy(dtype="float64")
        assert (np.isnan(u) == np.isnan(v)).all(), (s, c)
        ok = ~np.isnan(u)
        if ok.any():
            worst = max(worst, float(np.max(np.abs(u[ok] / v[ok] - 1.0))))
print("last 2000 bars: side/exit identical; worst relative price difference", worst)
