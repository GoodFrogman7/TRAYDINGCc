"""Shared setup for the skeptic's scripts. Validation window only: the holdout is never loaded."""
import json, sys, time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from desk.engine.runner import load_market, run_feed
from desk.data.store import VALIDATION_END, DESIGN_END
from desk.data import store
from desk.audit import harness
from desk.engine.core import Costs, Risk, attach
from desk.engine.metrics import summarize
from desk.strategies.s_trend_impulse_follow import STRATEGY

RES = json.loads((ROOT / "research/results/trend_impulse_follow.json").read_text())
CHOSEN = RES["wf_chosen"]
EQ0 = 10_000.0

def setup():
    market = load_market(end=VALIDATION_END)
    assert max(df.index[-1] for df in market.data.values()) < VALIDATION_END
    cells = harness.grid_cells(STRATEGY)
    intents = [STRATEGY.intents(market.data, dict(c)) for c in cells]
    return market, cells, intents

def wf_val(market, intents, costs=None, risk=None, base=None, delay=0):
    base = base or market.base
    its = intents if not delay else [{s: df.shift(delay) for s, df in it.items()} for it in intents]
    need = sorted({c["cell"] for c in CHOSEN if pd.Timestamp(c["test_start"], tz="UTC") >= DESIGN_END})
    feeds = {k: attach(base, its[k]) for k in need}
    parts = []
    for c in CHOSEN:
        t0, t1 = pd.Timestamp(c["test_start"], tz="UTC"), pd.Timestamp(c["test_end"], tz="UTC")
        if t0 < DESIGN_END: continue
        parts.append(run_feed(feeds[c["cell"]], STRATEGY, t0, t1, costs or Costs(), risk or Risk()))
    e, g, t = harness.stitch(parts, EQ0)
    s = summarize(e, t, EQ0, g)
    return s, t, e, g
