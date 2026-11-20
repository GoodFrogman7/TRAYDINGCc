"""Open the sealed holdout for the finalists. Once.

    python -m desk.audit.holdout s_a s_b s_c --unseal

Procedure (fixed in advance, identical for every finalist):
  1. choose parameters from the strategy's grid on the 18 months BEFORE the
     holdout starts, using the same objective as the walk-forward
  2. trade the holdout (2026-05-18 .. last bar) once with those parameters

Every opening is recorded in research/results/holdout_log.json. A strategy
that has already been run is refused, so the holdout cannot be mined.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
from dataclasses import replace
from pathlib import Path

import pandas as pd

from ..data import store
from ..data.store import VALIDATION_END
from ..engine.core import Costs, Risk, attach
from ..engine.runner import load_market, run_feed
from ..strategies.base import registry
from .harness import TRAIN_MONTHS, btc_regimes, buy_and_hold, by_regime, grid_cells, monte_carlo, objective

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "results"
LOG = OUT / "holdout_log.json"


def run_holdout(strategy, market, costs: Costs, risk: Risk) -> dict:
    cells = grid_cells(strategy)
    feeds = [attach(market.base, strategy.intents(market.data, c)) for c in cells]
    train0 = VALIDATION_END - pd.DateOffset(months=TRAIN_MONTHS)
    best, best_obj = 0, -math.inf
    for k, f in enumerate(feeds):
        obj = objective(run_feed(f, strategy, train0, VALIDATION_END, costs, risk)["summary"])
        if obj > best_obj:
            best, best_obj = k, obj
    r = run_feed(feeds[best], strategy, VALIDATION_END, None, costs, risk)
    x2 = run_feed(feeds[best], strategy, VALIDATION_END, None, replace(costs, fee_mult=2.0), risk)
    end = market.base.index[-1] + pd.Timedelta(hours=1)
    reg = btc_regimes(market)
    return {
        "name": strategy.name, "params": cells[best], "cell": best,
        "window": [VALIDATION_END.isoformat(), end.isoformat()],
        "data_asof": store.manifest()["asof_bar_cutoff_utc"],
        "holdout": r["summary"],
        "fees_x2": {k: x2["summary"].get(k, 0.0) for k in ("total_return", "max_dd", "n_trades")},
        "monte_carlo": monte_carlo(r["trades"], risk.equity0),
        "regimes_trend": by_regime(r["equity"], reg["trend"], risk.equity0) if len(r["equity"]) else {},
        "benchmark": buy_and_hold(market, VALIDATION_END, end, costs, risk.equity0),
        "passed": r["summary"].get("total_return", 0.0) > 0 and r["summary"].get("n_trades", 0) > 0,
        "_trades": r["trades"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--unseal", action="store_true", help="required: confirms the holdout is being opened on purpose")
    a = ap.parse_args(argv)
    if not a.unseal:
        raise SystemExit("refusing: pass --unseal to open the holdout")
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    already = {e["name"] for e in log}
    reg = registry()
    market = load_market(end=None)
    for n in a.names:
        st = reg.get(n) or importlib.import_module(f"desk.strategies.{n}").STRATEGY
        if st.name in already:
            print(f"{st.name}: holdout already opened for this strategy; refusing to run it again")
            continue
        res = run_holdout(st, market, Costs(), Risk())
        trades = res.pop("_trades")
        (OUT / "trades").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(trades).to_csv(OUT / "trades" / f"holdout_{st.name}.csv", index=False)
        res["opened_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
        (OUT / f"holdout_{st.name}.json").write_text(json.dumps(res, indent=1, default=float))
        log.append({"name": st.name, "opened_at_utc": res["opened_at_utc"]})
        LOG.write_text(json.dumps(log, indent=1))
        h = res["holdout"]
        print(f"{st.name:<28} holdout ret {h.get('total_return', 0):+7.2%}  dd {h.get('max_dd', 0):6.2%}  "
              f"trades {h.get('n_trades', 0):4d}  fees2x {res['fees_x2']['total_return']:+7.2%}  "
              f"hold basket {res['benchmark']['basket']['total_return']:+7.2%}  btc {res['benchmark']['btc']['total_return']:+7.2%}"
              f"  {'PASS' if res['passed'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
