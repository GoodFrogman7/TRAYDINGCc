"""Scratch probe (manual, network): does a 3000-bar live window equal the research parquet on the same bars?
Run from the repo root: PYTHONPATH=. python research/builder/probe_parity.py"""
import json

import numpy as np
import pandas as pd

from desk.data import store
from desk.data.download import MAX_REL_FUNDING, build_symbol
from desk.data.kraken import KrakenFutures
from desk.engine.costs import slip_series

k = KrakenFutures(timeout=15, max_retries=3)
fm = json.load(open("data/manifest.json"))["funding_model"]
for sym in ("PF_XBTUSD", "PF_ZECUSD"):
    full = store.load(sym)
    asof = int(full.index[-1].timestamp()) + 3600
    win, _ = build_symbol(k, sym, asof, asof - 3000 * 3600)
    f = fm["per_symbol"].get(sym, {})
    a, kk = f.get("a", fm["pooled_a"]), f.get("k", fm["pooled_k"])
    est = (a + kk * win["premium"].shift(1)).clip(-MAX_REL_FUNDING, MAX_REL_FUNDING)
    win["funding_is_est"] = win["funding_actual"].isna()
    win["funding"] = win["funding_actual"].fillna(est).fillna(0.0)
    for c in ("oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "premium"):
        win[c] = win[c].astype("float32")
    ref = full.reindex(win.index)
    print(sym, "rows", len(win), "cols same order:", list(win.columns) == list(ref.columns),
          "| extra/missing:", set(win.columns) ^ set(ref.columns))
    for c in ref.columns:
        x, y = win[c].to_numpy(dtype="float64"), ref[c].to_numpy(dtype="float64")
        bad = ~(np.isclose(x, y, rtol=1e-12, atol=0, equal_nan=True))
        if bad.any():
            print("   differs:", c, int(bad.sum()), "rows; first at", win.index[np.nonzero(bad)[0][0]],
                  "last at", win.index[np.nonzero(bad)[0][-1]])
    s_w, s_f = slip_series(win), slip_series(full).reindex(win.index)
    d = (s_w - s_f).abs()
    print("   slip_bps window vs full: max abs diff last 2000 rows", float(d.iloc[-2000:].max()),
          "| rows differing overall", int((d > 1e-12).sum()), "of", len(d), "| dtypes", dict(win.dtypes.astype(str))["oi"], dict(ref.dtypes.astype(str))["oi"])
