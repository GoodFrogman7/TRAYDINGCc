"""Look-ahead: harness.leak_test with several seeds + point-in-time check of the universe list."""
import sys, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from desk.engine.runner import load_market
from desk.data import store
from desk.data.store import VALIDATION_END
from desk.audit import harness
from desk.strategies.s_cross_weekend_follow_alts import STRATEGY

market = load_market(end=VALIDATION_END)
with store.ceiling(VALIDATION_END):
    for seed in (1, 7, 42, 2026):
        t0 = time.time()
        r = harness.leak_test(STRATEGY, market.data, seed=seed, n_targeted=120, n_other=6, n_random=4)
        print("seed", seed, {k: r[k] for k in ("passed", "mismatches", "probes", "cells", "forbidden_code")}, round(time.time() - t0, 1), "s", flush=True)
