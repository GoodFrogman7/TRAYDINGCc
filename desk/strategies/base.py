"""Strategy contract.

A strategy is a pure function from past bars to INTENTS. It never sees the
future and never touches money: the engine decides fills, sizes positions from
the attached stop, charges costs, and enforces the Guardian's limits.

`intents(data, p)` receives `data = {symbol: DataFrame}` (hourly bars, index =
bar open time, UTC; row t is fully known at the close of bar t) and returns
`{symbol: DataFrame}` with the same index and these columns:

  side   int8   +1 open long, -1 open short, 0 nothing        (decided at close of bar t)
  limit  float  entry limit price; NaN = market at next open
  stop   float  protective stop price. REQUIRED when side != 0
  tp     float  take-profit price; NaN = none
  trail  float  new stop level for an open position (engine only ever tightens); NaN = no change
  exit   bool   close any open position at the next bar's open

An intent at bar t can only trade from bar t+1 onward. One position per symbol;
entry intents are ignored while a position or a pending order exists.

Available columns per symbol (see docs/DATA.md): open high low close volume
mark_close spot_close premium funding funding_actual funding_is_est oi liq_vol
ls_ratio buy_vol sell_vol bid_10k ask_10k bid_100k ask_100k bar_missing.
Some start later than the candles (oi ~2023-03, ls_ratio/bid/ask ~2023-08):
strategies must emit no signal while a required input is NaN.
"""
from __future__ import annotations

import importlib
import pkgutil

import pandas as pd

from ..engine.core import blank_intents  # re-export for strategy authors

__all__ = ["Strategy", "blank_intents", "registry"]


class Strategy:
    name: str = ""
    idea: str = ""            # the idea in one sentence
    cause: str = ""           # why the edge exists, in one sentence
    loser: str = ""           # who is on the losing side
    regime: str = ""          # trending | ranging | wild
    valid_bars: int = 1       # bars a limit entry stays working
    max_hold: int = 0         # time stop in bars (0 = none)
    params: dict = {}         # default parameters
    grid: dict = {}           # neighbourhood to test: {param: [values...]}, defaults included
    needs: tuple = ()         # optional columns required, e.g. ("oi", "liq_vol")

    def intents(self, data: dict[str, pd.DataFrame], p: dict) -> dict[str, pd.DataFrame]:
        raise NotImplementedError


def registry() -> dict[str, Strategy]:
    """Import every module in desk.strategies named s_* and collect its STRATEGY."""
    import desk.strategies as pkg
    out: dict[str, Strategy] = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name.startswith("s_"):
            mod = importlib.import_module(f"desk.strategies.{m.name}")
            s = getattr(mod, "STRATEGY", None)
            if s is not None:
                out[s.name] = s
    return out
