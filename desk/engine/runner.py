"""Run one strategy with one parameter set over a window."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..data import store
from .core import Costs, Engine, Feed, FeedBase, Risk, attach, make_base
from .costs import slip_table
from .metrics import summarize


@dataclass
class Market:
    """Everything a run needs that does not depend on the strategy."""
    data: dict[str, pd.DataFrame]
    base: FeedBase


def load_market(end: pd.Timestamp | None = None, syms: list[str] | None = None) -> Market:
    """Bars strictly before `end`. Nothing later is in memory, so no run can read it."""
    data = store.load_all(end=end, syms=syms)
    # no new entries outside the month's universe, nor on hours the venue printed no candle
    tradable = {s: store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool) for s, df in data.items()}
    base = make_base(data, tradable=tradable, slip_bps=slip_table(data), end=end)
    return Market(data=data, base=base)


def prepare(strategy, params: dict | None, market: Market) -> Feed:
    """Compute intents once on the full (causal) history and attach them to the bars."""
    p = {**strategy.params, **(params or {})}
    return attach(market.base, strategy.intents(market.data, p))


def run_feed(feed: Feed, strategy, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
             costs: Costs | None = None, risk: Risk | None = None, log_events: bool = False) -> dict:
    """Trade bars in [start, end): start flat, close everything at the end."""
    idx = feed.index
    i0 = 0 if start is None else int(idx.searchsorted(start))
    i1 = feed.n if end is None else int(idx.searchsorted(end))
    risk = risk or Risk()
    eng = Engine(costs or Costs(), risk, valid_bars=strategy.valid_bars, max_hold=strategy.max_hold,
                 log_events=log_events)
    if i1 > i0:
        eng.run(feed, i0, i1, close_at_end=True)
    eq = pd.Series(eng.equity_curve[i0:i1] if eng.equity_curve is not None else [], index=idx[i0:i1], dtype="float64")
    gross = pd.Series(eng.gross_curve[i0:i1] if eng.gross_curve is not None else [], index=idx[i0:i1], dtype="float64")
    return {"summary": summarize(eq, eng.trades, risk.equity0, gross), "trades": eng.trades,
            "equity": eq, "gross": gross, "events": eng.events}


def run(strategy, params: dict | None, market: Market, start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None, costs: Costs | None = None, risk: Risk | None = None,
        log_events: bool = False) -> dict:
    out = run_feed(prepare(strategy, params, market), strategy, start, end, costs, risk, log_events)
    out["params"] = {**strategy.params, **(params or {})}
    return out
