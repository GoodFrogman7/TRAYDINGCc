"""Design-window engine harness (uses store.load_design only). Runs a draft strategy through the desk's
real engine with real costs so the numbers in FINDINGS.md are after fees, funding and slippage."""
from __future__ import annotations

import numpy as np
import pandas as pd

from desk.data import store
from desk.engine.core import Costs, make_base
from desk.engine.costs import slip_table
from desk.engine.runner import Market, run

_M = None


def market() -> Market:
    global _M
    if _M is None:
        data = store.load_design()
        tradable = {s: store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool) for s, df in data.items()}
        _M = Market(data=data, base=make_base(data, tradable=tradable, slip_bps=slip_table(data), end=store.DESIGN_END))
    return _M


class Delayed:
    """Wrap a strategy so every intent is emitted one bar later (stale-entry robustness)."""
    def __init__(self, s):
        self.s = s
        self.params, self.valid_bars, self.max_hold, self.name = s.params, s.valid_bars, s.max_hold, s.name + "_late"

    def intents(self, data, p):
        return {k: v.shift(1).fillna({"side": 0, "exit": False}).astype({"side": "int8", "exit": bool}) for k, v in self.s.intents(data, p).items()}


def report(strategy, params=None, label="", costs=None, verbose=True) -> dict:
    res = run(strategy, params, market(), start=pd.Timestamp("2022-05-01", tz="UTC"), end=store.DESIGN_END, costs=costs)
    s, tr = res["summary"], pd.DataFrame(res["trades"])
    row = dict(label=label or strategy.name, n=s["n_trades"], ret_pct=round(s["total_return"] * 100, 2), maxdd_pct=round(s["max_dd"] * 100, 2),
               sharpe=round(s["sharpe"], 2), win=round(s.get("win_rate", 0), 3), avg_r=round(s.get("avg_r", 0), 3), pf=round(s.get("profit_factor", 0), 2),
               streak=s.get("longest_losing_streak", 0), bars=round(s.get("avg_bars_held", 0), 1))
    if len(tr):
        tr["year"] = pd.to_datetime(tr["entry_time"]).dt.year
        notional = tr["qty"] * tr["entry_price"]
        tr["gross_bps"] = tr["pnl_gross"] / notional * 1e4
        tr["net_bps"] = tr["pnl"] / notional * 1e4
        row["gross_bps"] = round(tr["gross_bps"].mean(), 1); row["net_bps"] = round(tr["net_bps"].mean(), 1)
        for y in (2022, 2023, 2024):
            g = tr[tr.year == y]
            row[f"y{y}"] = f"{len(g)}/{g.pnl.sum() / 100:.1f}%"
        row["long"] = f"{(tr.side > 0).sum()}/{tr.pnl[tr.side > 0].sum() / 100:.1f}%"
        row["short"] = f"{(tr.side < 0).sum()}/{tr.pnl[tr.side < 0].sum() / 100:.1f}%"
        row["exits"] = str(s.get("exit_reasons"))
    res["row"], res["tr"] = row, tr
    return res


def table(rows):
    pd.set_option("display.width", 320); pd.set_option("display.max_colwidth", 90); pd.set_option("display.max_columns", 40)
    print(pd.DataFrame(rows).to_string(index=False))
