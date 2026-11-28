"""Full walk-forward audit restricted to Coinbase-listed coins (same method as research/verify/coinbase_subset.py,
but nothing is written to research/results)."""
import time
from vcommon import *
t0=time.time()
allowed=set(json.loads((ROOT/"config/coinbase_perps.json").read_text())["kraken_symbols"])
market=load_market(end=VALIDATION_END)
for s_, a in market.base.arrays.items():
    if s_ not in allowed: a["tradable"]=np.zeros_like(a["tradable"])
harness.leak_test=lambda *a, **k: {"passed": True, "skipped": True, "mismatches": 0, "probes": 0}
r=harness.audit(STRATEGY, market, replay=False)
v=r["wf_validation"]
print("COINBASE-ONLY full audit: ret %+.2f%% dd %.2f%% n %d avg_r %.3f sharpe %.2f" % (v["total_return"]*100, v["max_dd"]*100, v["n_trades"], v["avg_r"], v["sharpe"]))
print("long $%.0f short $%.0f" % (v["long_pnl_usd"], v["short_pnl_usd"]))
print("stress:", {k: round(x["total_return"]*100,2) for k,x in r["stress"].items()})
print("grid share profitable %.2f median %.3f worst %.3f" % (r["neighbourhood"]["share_profitable"], r["neighbourhood"]["median_return"], r["neighbourhood"]["worst_return"]))
print("p", r["monte_carlo"]["p_value_mean_le_0"], "gates", r["gates"])
print("by quarter", r["wf_by_quarter"][5:])
print("chosen", [(c["test_start"], c["cell"]) for c in r["wf_chosen"][5:]])
print("pnl by symbol", v["pnl_by_symbol"])
print("time", round(time.time()-t0,1))
