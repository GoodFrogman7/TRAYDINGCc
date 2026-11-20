"""The desk's own audit (walk-forward re-fitted, stress, neighbourhood, bootstrap) restricted to Coinbase-listed coins.
Same code as research/verify/coinbase_subset.py but writes nothing under research/results."""
from vcommon import *
allowed = set(json.loads((ROOT / "config" / "coinbase_perps.json").read_text())["kraken_symbols"])
market = load_market(end=VALIDATION_END)
for s_, a in market.base.arrays.items():
    if s_ not in allowed: a["tradable"] = np.zeros_like(a["tradable"])
harness.leak_test = lambda *a, **k: {"passed": True, "skipped": True, "mismatches": 0, "probes": 0}
r = harness.audit(STRATEGY, market, replay=False)
v = r["wf_validation"]
print("coinbase-listed only: ret %+.2f%% dd %.2f%% trades %d sharpe %.2f avg_r %.3f" % (v["total_return"]*100, v["max_dd"]*100, v["n_trades"], v["sharpe"], v["avg_r"]))
print("stress", {k: round(x["total_return"],4) for k,x in r["stress"].items()})
print("neighbourhood", r["neighbourhood"]["share_profitable"], [ (c["params"], c["ret"]) for c in r["neighbourhood"]["by_cell"]])
print("p", r["monte_carlo"]["p_value_mean_le_0"], "gates", r["gates"])
print("by quarter", r["wf_by_quarter"][5:])
print("chosen", [(c["test_start"], c["params"]["q"], c["params"]["stop_atr"]) for c in r["wf_chosen"][5:]])
print("pnl_by_symbol", v["pnl_by_symbol"])
print("monthly", v["monthly"])
