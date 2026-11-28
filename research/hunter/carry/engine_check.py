"""Run a draft strategy through the real desk engine on the DESIGN window only (fees, funding, slippage, Guardian on)."""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from desk.data import store
from desk.engine.core import Costs, Risk, make_base
from desk.engine.costs import slip_table
from desk.engine.runner import Market, run

_M = None

def market() -> Market:
    global _M
    if _M is None:
        data = store.load_design()                      # design window only
        assert max(df.index.max() for df in data.values()) < store.DESIGN_END
        tradable = {s: store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool) for s, df in data.items()}
        _M = Market(data=data, base=make_base(data, tradable=tradable, slip_bps=slip_table(data), end=store.DESIGN_END))
    return _M

def check(strategy, params=None, label="", costs=None, risk=None, max_hold=None):
    if max_hold is not None:
        strategy.max_hold = max_hold
    res = run(strategy, params, market(), costs=costs, risk=risk)
    t = pd.DataFrame(res["trades"]); s = res["summary"]
    row = dict(label=label or strategy.name, n=len(t))
    if len(t):
        t["year"] = pd.to_datetime(t["entry_time"]).dt.year
        t["notional"] = t["qty"] * t["entry_price"]
        t["gross_bps"] = t["pnl_gross"] / t["notional"] * 1e4
        t["net_bps"] = t["pnl"] / t["notional"] * 1e4
        row.update(win=round(s["win_rate"], 2), avgR=round(s["avg_r"], 3), gross_bp=round(t.gross_bps.mean(), 1),
                   net_bp=round(t.net_bps.mean(), 1), ret=round(s["total_return"] * 100, 1),
                   dd=round(s["max_dd"] * 100, 1), sharpe=round(s["sharpe"], 2), streak=s["longest_losing_streak"],
                   stop=round((t.reason == "stop").mean(), 2), guard=int((t.reason == "guardian").sum()),
                   hold=round(s["avg_bars_held"], 1), notl=int(t.notional.median()))
        for y in (2022, 2023, 2024):
            g = t[t.year == y]
            row[f"y{y}"] = f"{g.pnl.sum()/100:.1f}%/{len(g)}"
    res["row"] = row; res["tdf"] = t
    return res

def table(rows):
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40)
    print(pd.DataFrame([r["row"] for r in rows]).to_string(index=False))
