"""Re-run the walk-forward audit allowing entries only in coins Coinbase lists as perpetual-style futures.

    python research/verify/coinbase_subset.py trend_impulse_follow ...

Validation window only (the sealed holdout is not loaded). The look-ahead test is skipped here because the
strategy code is unchanged and already passed it. Writes research/results/coinbase_subset.json.
"""
import importlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desk.audit import harness                      # noqa: E402
from desk.data.store import VALIDATION_END          # noqa: E402
from desk.engine.runner import load_market          # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
allowed = set(json.loads((ROOT / "config" / "coinbase_perps.json").read_text())["kraken_symbols"])
market = load_market(end=VALIDATION_END)
for s, a in market.base.arrays.items():
    if s not in allowed:
        a["tradable"] = np.zeros_like(a["tradable"])
harness.leak_test = lambda *a, **k: {"passed": True, "skipped": True, "mismatches": 0, "probes": 0}
out_path = ROOT / "research" / "results" / "coinbase_subset.json"
out = json.loads(out_path.read_text()) if out_path.exists() else {}
for name in sys.argv[1:]:
    st = importlib.import_module(f"desk.strategies.s_{name}").STRATEGY
    r = harness.audit(st, market, replay=False)
    v = r["wf_validation"]
    out[name] = {"total_return": v.get("total_return"), "max_dd": v.get("max_dd"), "n_trades": v.get("n_trades"),
                 "sharpe": v.get("sharpe"), "avg_r": v.get("avg_r"), "fees_x2": r["stress"]["fees_x2"]["total_return"],
                 "one_bar_late": r["stress"]["one_bar_late"]["total_return"],
                 "grid_share_profitable": r["neighbourhood"]["share_profitable"],
                 "p_value": r["monte_carlo"].get("p_value_mean_le_0"),
                 "gates_excluding_lookahead": {k: v2 for k, v2 in r["gates"].items() if k not in ("no_lookahead", "all_passed")},
                 "pnl_by_symbol": v.get("pnl_by_symbol"), "allowed_symbols": sorted(allowed)}
    print(f"{name:<28} coinbase-listed only: ret {v.get('total_return', 0):+.2%} dd {v.get('max_dd', 0):.2%} "
          f"trades {v.get('n_trades', 0)} fees2x {out[name]['fees_x2']:+.2%} late {out[name]['one_bar_late']:+.2%} "
          f"grid+ {out[name]['grid_share_profitable']:.0%} p {out[name]['p_value']:.3f}", flush=True)
    out_path.write_text(json.dumps(out, indent=1, default=float))
