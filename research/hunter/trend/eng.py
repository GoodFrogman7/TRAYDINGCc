"""Run a candidate through the desk's own engine on the DESIGN window only (costs, funding, slippage, Guardian)."""
from __future__ import annotations
from dataclasses import replace
import numpy as np, pandas as pd
from lib import load, store
from desk.engine.core import Costs, Risk, make_base
from desk.engine.costs import slip_table
from desk.engine.runner import Market, run

_M = {}

def market() -> Market:
    if "m" not in _M:
        data = {s: df.drop(columns=["trd"]) for s, df in load().items()}
        tradable = {s: load()[s]["trd"] for s in data}
        base = make_base(data, tradable=tradable, slip_bps=slip_table(data), end=store.DESIGN_END)
        _M["m"] = Market(data=data, base=base)
    return _M["m"]

def line(strategy, params=None, costs=None, risk=None, label=""):
    res = run(strategy, params, market(), costs=costs, risk=risk)
    s, tr = res["summary"], pd.DataFrame(res["trades"])
    out = dict(label=label, n=s["n_trades"], win=round(s["win_rate"], 3), avgR=round(s["avg_r"], 3),
               ret=round(s["total_return"] * 100, 1), dd=round(s["max_dd"] * 100, 1), streak=s["longest_losing_streak"],
               hold=round(s["avg_bars_held"], 1), L=round(s["long_pnl_usd"]), S=round(s["short_pnl_usd"]),
               fees=round(s["fees_usd"]), fund=round(s["funding_usd"]))
    if len(tr):
        tr["y"] = pd.to_datetime(tr["entry_time"]).dt.year
        for y in (2022, 2023, 2024):
            out[f"p{y%100}"] = round(tr.loc[tr.y == y, "pnl"].sum())
        out["gross_bps"] = round((tr["pnl_gross"] / (tr["qty"] * tr["entry_price"])).mean() * 1e4, 1)
        out["exits"] = dict(tr["reason"].value_counts())
    return out, res

def show(strategy, variants: list[tuple[str, dict]], stress=True):
    rows = []
    for lab, p in variants:
        o, _ = line(strategy, p, label=lab); rows.append(o)
    if stress:
        lab, p = variants[0]
        o, _ = line(strategy, p, risk=Risk(guardian=False), label=lab + " | no guardian"); rows.append(o)
        o, _ = line(strategy, p, costs=Costs(fee_mult=2.0), label=lab + " | fees x2"); rows.append(o)
        o, _ = line(strategy, p, costs=Costs(fee_mult=0, slip_mult=0, funding_mult=0), label=lab + " | no costs"); rows.append(o)
    df = pd.DataFrame(rows)
    ex = df.pop("exits")
    print(df.to_string(index=False))
    print("exits(default):", ex.iloc[0])
    return df
