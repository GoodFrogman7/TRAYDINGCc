"""Audit strategies and write results.

    python -m desk.audit.run s_my_idea            # one registered strategy (module desk/strategies/s_my_idea.py)
    python -m desk.audit.run --all                # every registered strategy
    python -m desk.audit.run --ref                # the reference template (sanity check)

Writes research/results/<name>.json and research/results/trades/<name>.csv.
The sealed holdout is never loaded here.
"""
from __future__ import annotations

import argparse
import importlib
import json
import time
from pathlib import Path

import pandas as pd

from ..data.store import VALIDATION_END
from ..engine.runner import load_market
from ..strategies.base import registry
from .harness import audit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "results"


def _json(o):
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(type(o))


def save(res: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trades").mkdir(exist_ok=True)
    pd.DataFrame(res.pop("_trades_all")).to_csv(OUT / "trades" / f"{res['name']}.csv", index=False)
    res.pop("_trades_validation", None)
    eq = res.pop("_equity_all")
    if len(eq):
        eq.resample("1D").last().round(2).to_csv(OUT / "trades" / f"{res['name']}_equity_daily.csv", header=["equity"])
    res["audited_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    p = OUT / f"{res['name']}.json"
    p.write_text(json.dumps(res, indent=1, default=_json))
    return p


def line(res: dict) -> str:
    v, g, s = res["wf_validation"], res["gates"], res["scores"]
    failed = [k for k, ok in g.items() if not ok and k != "all_passed"]
    return (f"{res['name']:<28} val ret {v.get('total_return', 0):+7.2%}  dd {v.get('max_dd', 0):6.2%}  "
            f"trades {v.get('n_trades', 0):4d}  sharpe {v.get('sharpe', 0):5.2f}  fees2x "
            f"{res['stress']['fees_x2']['total_return']:+7.2%}  grid+ {res['neighbourhood']['share_profitable']:.0%}  "
            f"score {s['total']:2d}/25  {'PASS' if g['all_passed'] else 'FAIL: ' + ','.join(failed)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ref", action="store_true")
    a = ap.parse_args(argv)
    reg = registry()
    if a.ref:
        strategies = [importlib.import_module("desk.strategies.ref_donchian").STRATEGY]
    elif a.all:
        strategies = list(reg.values())
    else:
        strategies = []
        for n in a.names:
            n = n.removesuffix(".py").split("/")[-1]
            mod = importlib.import_module(f"desk.strategies.{n}") if n.startswith("s_") else None
            st = mod.STRATEGY if mod else reg.get(n)
            if st is None:
                raise SystemExit(f"unknown strategy {n}; registered: {sorted(reg)}")
            strategies.append(st)
    market = load_market(end=VALIDATION_END)
    for st in strategies:
        t = time.time()
        res = audit(st, market)
        print(line(res), f"({time.time() - t:.0f}s)", flush=True)
        save(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
