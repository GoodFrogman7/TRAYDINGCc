"""Run prototype strategies through the desk's REAL engine on the DESIGN window only.

Data comes from store.load_design() (bars before 2025-01-01); the feed is built
with end=DESIGN_END so nothing later can be in memory. Costs = engine defaults
(taker 5 bps, maker 2 bps, order-book slippage, x2 on stops, hourly funding).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.data import store  # noqa: E402
from desk.engine.core import Costs, Risk, attach, make_base  # noqa: E402
from desk.engine.costs import slip_table  # noqa: E402
from desk.engine.runner import Market, run_feed  # noqa: E402

_MKT = None


def market() -> Market:
    global _MKT
    if _MKT is None:
        data = store.load_design()
        tradable = {s: store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool) for s, df in data.items()}
        base = make_base(data, tradable=tradable, slip_bps=slip_table(data), end=store.DESIGN_END)
        _MKT = Market(data=data, base=base)
    return _MKT


def delay_intents(intents: dict[str, pd.DataFrame], k: int = 1) -> dict[str, pd.DataFrame]:
    """Shift every intent k bars later (the 'one bar late' robustness check)."""
    return {s: it.shift(k).assign(side=lambda d: d["side"].fillna(0).astype(np.int8),
                                  exit=lambda d: d["exit"].fillna(False).astype(bool)) for s, it in intents.items()}


def run(strategy, params: dict | None = None, delay: int = 0, costs: Costs | None = None,
        risk: Risk | None = None, start=None, end=None) -> dict:
    m = market()
    p = {**strategy.params, **(params or {})}
    it = strategy.intents(m.data, p)
    if delay:
        it = delay_intents(it, delay)
    feed = attach(m.base, it)
    return run_feed(feed, strategy, start, end, costs, risk)


def trades_df(res: dict) -> pd.DataFrame:
    t = pd.DataFrame(res["trades"])
    if len(t):
        t["entry_time"] = pd.to_datetime(t["entry_time"])
        t["year"] = t["entry_time"].dt.year
        t["ret_bps"] = t["side"] * (t["exit_price"] / t["entry_price"] - 1) * 1e4   # after slippage, before fees
        t["net_bps"] = t["pnl"] / (t["qty"] * t["entry_price"]) * 1e4
        t["major"] = t["symbol"].isin(["PF_XBTUSD", "PF_ETHUSD"])
    return t


def line(res: dict, label: str = "") -> dict:
    s = res["summary"]
    t = trades_df(res)
    d = dict(label=label, n=s.get("n_trades", 0), ret=s.get("total_return", 0) * 100, ann=s.get("annual_return", 0) * 100,
             dd=s.get("max_dd", 0) * 100, win=s.get("win_rate", 0), avgR=s.get("avg_r", 0), pf=s.get("profit_factor", 0),
             streak=s.get("longest_losing_streak", 0), hold=s.get("avg_bars_held", 0), worstR=s.get("worst_r", 0))
    if len(t):
        d["gross_bps"] = t["ret_bps"].mean()
        d["net_bps"] = t["net_bps"].mean()
        for y in (2022, 2023, 2024):
            g = t[t.year == y]
            d[f"R{y}"] = g["r"].sum()
            d[f"n{y}"] = len(g)
        d["R_long"] = t.loc[t.side > 0, "r"].sum()
        d["R_short"] = t.loc[t.side < 0, "r"].sum()
        d["n_short"] = int((t.side < 0).sum())
        d["R_maj"] = t.loc[t.major, "r"].sum()
        d["stops"] = s.get("exit_reasons", {}).get("stop", 0)
    return d


def show(rows: list[dict]) -> None:
    with pd.option_context("display.width", 330, "display.max_columns", 50, "display.float_format", lambda v: f"{v:,.2f}"):
        print(pd.DataFrame(rows).to_string(index=False))
