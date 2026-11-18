"""One bar-by-bar trading simulator shared by the backtests and the paper bot.

The SAME `Engine.run` processes four years of history in a backtest and the one
new hourly bar in the paper bot, so paper results are directly comparable to
backtest results.

Timing (this is what makes look-ahead structurally hard):

  * A strategy sees bars up to and including bar t and emits an INTENT at t.
  * The engine turns that intent into an order that can only fill in bar t+1
    or later. Nothing decided at t can trade at a price from bar t.

Order of events inside bar i:

  a. exits flagged earlier (signal / time stop / guardian) fill at open[i]
  b. pending entry orders try to fill against bar i
  c. funding for bar i is charged on every open position
  d. protective stops and take-profits are checked against high/low of bar i
  e. intents emitted at the close of bar i become orders for bar i+1
  f. equity is marked to close[i]; the Guardian checks its limits

Fill model (deliberately pessimistic where the bar hides the true path):

  * market entry / exit   open price moved against us by slippage; taker fee
  * resting limit         fills only if price trades THROUGH the limit by
                          `limit_through_bps`; fills at the limit; maker fee
  * limit already marketable at the open -> fills at the open (plus slippage,
    never worse than the limit); taker fee
  * stop                  fills at the stop (or at the open if the bar gaps
                          through it), moved against us by slippage x
                          `stop_slip_mult`; taker fee
  * if a stop and a take-profit are both touched in one bar -> the stop wins
  * a limit entry that fills inside a bar whose range also touches its stop is
    treated as stopped in that same bar
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

NAN = float("nan")


@dataclass
class Costs:
    taker_fee: float = 0.0005        # Kraken Futures tier-0 taker, 0.05% (feeschedules endpoint, 2026-11-18)
    maker_fee: float = 0.0002        # tier-0 maker, 0.02%
    fee_mult: float = 1.0            # 2.0 = the "fees doubled" stress test
    slip_mult: float = 1.0
    funding_mult: float = 1.0
    stop_slip_mult: float = 2.0      # stops fill in fast markets
    limit_through_bps: float = 1.0   # required trade-through for a resting limit


@dataclass
class Risk:
    equity0: float = 10_000.0
    risk_per_trade: float = 0.005    # fraction of equity lost if the stop is hit
    compounding: bool = False        # False: size off equity0 (comparable R per trade)
    max_pos_mult: float = 1.0        # one position's notional <= this x equity
    max_gross_mult: float = 3.0      # sum of |notional| <= this x equity
    max_positions: int = 10
    min_stop_pct: float = 0.002      # reject stops closer than 0.2% (unrealistic size / noise)
    max_stop_pct: float = 0.25
    min_notional: float = 10.0
    guardian: bool = True
    daily_loss_limit: float = 0.03   # halt at -3% on the UTC day
    max_consec_losses: int = 3       # halt after 3 losing trades in a row
    halt_sticky: bool = False        # True (live/paper): stay halted until a human resumes


@dataclass
class Order:
    symbol: str
    side: int
    limit: float          # NaN = market at next open
    stop: float
    tp: float             # NaN = none
    valid_left: int
    created: str
    tag: str = ""


@dataclass
class Position:
    symbol: str
    side: int
    qty: float
    entry_price: float
    entry_time: str
    stop: float
    stop0: float
    tp: float
    risk_usd: float
    maker_entry: bool
    limit_entry: bool
    fees: float = 0.0
    funding: float = 0.0
    bars_held: int = 0
    last_price: float = 0.0
    exit_pending: str = ""
    new: bool = False     # opened during the bar currently being processed
    tag: str = ""


@dataclass
class State:
    cash: float                      # equity0 + realised PnL - fees - funding
    equity: float                    # cash + unrealised, marked at the last close
    positions: dict[str, Position] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    day: int = -1
    day_start_equity: float = 0.0
    consec_losses: int = 0
    halted: bool = False
    halt_reason: str = ""
    halt_day: int = -1
    last_time: str = ""
    n_trades: int = 0

    def to_json(self) -> dict:
        d = asdict(self)
        return _clean(d)

    @staticmethod
    def from_json(d: dict) -> "State":
        d = dict(d)
        d["positions"] = {k: Position(**_unclean(v)) for k, v in d.get("positions", {}).items()}
        d["orders"] = {k: Order(**_unclean(v)) for k, v in d.get("orders", {}).items()}
        return State(**d)


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


def _unclean(d: dict) -> dict:
    return {k: (NAN if v is None and k in ("limit", "tp") else v) for k, v in d.items()}


@dataclass
class SymbolFeed:
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    funding: np.ndarray
    slip_bps: np.ndarray
    valid: np.ndarray      # a real bar exists for this symbol at this index
    tradable: np.ndarray   # symbol is in the point-in-time universe (new entries allowed)
    side: np.ndarray       # intents emitted at the close of the bar
    limit: np.ndarray
    stop: np.ndarray
    tp: np.ndarray
    trail: np.ndarray
    exit: np.ndarray


def _index_helpers(index: pd.DatetimeIndex) -> tuple[np.ndarray, list[str]]:
    ns = index.asi8 if index.unit == "ns" else index.as_unit("ns").asi8
    return (ns // (86_400 * 10**9)).astype(np.int64), [t.isoformat() for t in index]


class Feed:
    """Bars + intents for a set of symbols on one shared hourly index."""

    def __init__(self, index: pd.DatetimeIndex, sym: dict[str, SymbolFeed],
                 helpers: tuple[np.ndarray, list[str]] | None = None):
        self.index = index
        self.sym = sym
        self.n = len(index)
        self.day_id, self.times = helpers or _index_helpers(index)
        ev: dict[int, list[str]] = {}
        for s, f in sym.items():
            mask = (f.side != 0) | f.exit | ~np.isnan(f.trail)
            for i in np.nonzero(mask & f.valid)[0]:
                ev.setdefault(int(i), []).append(s)
        self.events = ev


INTENT_COLS = ["side", "limit", "stop", "tp", "trail", "exit"]


def blank_intents(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "side": np.zeros(len(index), dtype=np.int8),
        "limit": np.full(len(index), NAN), "stop": np.full(len(index), NAN),
        "tp": np.full(len(index), NAN), "trail": np.full(len(index), NAN),
        "exit": np.zeros(len(index), dtype=bool),
    }, index=index)


@dataclass
class FeedBase:
    """Prices, funding, costs and universe membership aligned on one hourly
    index. Built once and reused across many parameter runs."""
    index: pd.DatetimeIndex
    arrays: dict[str, dict[str, np.ndarray]]
    helpers: tuple | None = None


def make_base(data: dict[str, pd.DataFrame], tradable: dict[str, pd.Series] | None = None,
              slip_bps: dict[str, pd.Series] | float = 3.0,
              start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> FeedBase:
    """`end` is exclusive."""
    lo = min(df.index[0] for df in data.values())
    hi = max(df.index[-1] for df in data.values())
    if start is not None:
        lo = max(lo, start)
    if end is not None:
        hi = min(hi, end - pd.Timedelta(hours=1))
    index = pd.date_range(lo, hi, freq="h", name="time")
    arrays: dict[str, dict[str, np.ndarray]] = {}
    for s, df in data.items():
        d = df.reindex(index)
        valid = d["close"].notna().to_numpy()
        if not valid.any():
            continue
        if isinstance(slip_bps, dict):
            sl = slip_bps[s].reindex(index).ffill().bfill().to_numpy(dtype="float64")
        else:
            sl = np.full(len(index), float(slip_bps))
        tr = np.ones(len(index), dtype=bool) if tradable is None else \
            tradable[s].reindex(index).fillna(False).to_numpy(dtype=bool)
        arrays[s] = dict(
            o=d["open"].to_numpy(dtype="float64"), h=d["high"].to_numpy(dtype="float64"),
            l=d["low"].to_numpy(dtype="float64"), c=d["close"].to_numpy(dtype="float64"),
            funding=np.nan_to_num(d["funding"].to_numpy(dtype="float64"), nan=0.0) if "funding" in d
            else np.zeros(len(index)),
            slip_bps=np.nan_to_num(sl, nan=3.0), valid=valid, tradable=tr & valid)
    return FeedBase(index, arrays, _index_helpers(index))


def attach(base: FeedBase, intents: dict[str, pd.DataFrame]) -> Feed:
    n = len(base.index)
    sym: dict[str, SymbolFeed] = {}
    for s, a in base.arrays.items():
        it = intents.get(s)
        if it is None or not len(it):
            sym[s] = SymbolFeed(**a, side=np.zeros(n, dtype=np.int8), limit=np.full(n, NAN), stop=np.full(n, NAN),
                                tp=np.full(n, NAN), trail=np.full(n, NAN), exit=np.zeros(n, dtype=bool))
            continue
        it = it.reindex(base.index)
        sym[s] = SymbolFeed(
            **a,
            side=np.nan_to_num(it["side"].to_numpy(dtype="float64"), nan=0.0).astype(np.int8),
            limit=it["limit"].to_numpy(dtype="float64"), stop=it["stop"].to_numpy(dtype="float64"),
            tp=it["tp"].to_numpy(dtype="float64"), trail=it["trail"].to_numpy(dtype="float64"),
            exit=np.nan_to_num(it["exit"].to_numpy(dtype="float64"), nan=0.0).astype(bool))
    return Feed(base.index, sym, base.helpers)


def build_feed(data: dict[str, pd.DataFrame], intents: dict[str, pd.DataFrame],
               tradable: dict[str, pd.Series] | None = None,
               slip_bps: dict[str, pd.Series] | float = 3.0,
               start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> Feed:
    return attach(make_base(data, tradable, slip_bps, start, end), intents)


def _adverse(price: float, direction: int, bps: float) -> float:
    """Move `price` against a trade in `direction` (+1 buy, -1 sell)."""
    return price * (1.0 + direction * bps / 1e4)


class Engine:
    def __init__(self, costs: Costs | None = None, risk: Risk | None = None,
                 valid_bars: int = 1, max_hold: int = 0, state: State | None = None,
                 log_events: bool = False):
        self.costs = costs or Costs()
        self.risk = risk or Risk()
        self.valid_bars = max(1, int(valid_bars))
        self.max_hold = int(max_hold)
        self.state = state or State(cash=self.risk.equity0, equity=self.risk.equity0,
                                    day_start_equity=self.risk.equity0)
        self.log_events = log_events
        self.trades: list[dict] = []
        self.events: list[dict] = []
        self.equity_curve: np.ndarray | None = None
        self.gross_curve: np.ndarray | None = None

    # ------------------------------------------------------------------ utils
    def _ev(self, time: str, symbol: str, kind: str, **detail) -> None:
        if self.log_events:
            self.events.append({"time": time, "symbol": symbol, "event": kind, **detail})

    def _base_equity(self) -> float:
        return self.state.equity if self.risk.compounding else self.risk.equity0

    def _gross(self) -> float:
        return sum(abs(p.qty) * p.last_price for p in self.state.positions.values())

    def _halt(self, reason: str, t: str, day: int) -> None:
        st = self.state
        if st.halted:
            return
        st.halted, st.halt_reason, st.halt_day = True, reason, day
        for s in list(st.orders):
            self._ev(t, s, "order_cancelled", reason="guardian halt: " + reason)
            del st.orders[s]
        for p in st.positions.values():
            if not p.exit_pending:
                p.exit_pending = "guardian"
        self._ev(t, "*", "guardian_halt", reason=reason)

    def resume(self) -> None:
        """Human override: clear a Guardian halt."""
        st = self.state
        st.halted, st.halt_reason, st.halt_day, st.consec_losses = False, "", -1, 0

    def _close(self, pos: Position, price: float, t: str, reason: str, maker: bool) -> None:
        st, c = self.state, self.costs
        fee = pos.qty * price * (c.maker_fee if maker else c.taker_fee) * c.fee_mult
        gross = pos.side * pos.qty * (price - pos.entry_price)
        st.cash += gross - fee
        pos.fees += fee
        net = gross - pos.fees - pos.funding
        self.trades.append({
            "symbol": pos.symbol, "side": pos.side, "qty": pos.qty,
            "entry_time": pos.entry_time, "entry_price": pos.entry_price,
            "exit_time": t, "exit_price": price, "reason": reason,
            "stop0": pos.stop0, "risk_usd": pos.risk_usd, "bars_held": pos.bars_held,
            "pnl_gross": gross, "fees": pos.fees, "funding": pos.funding, "pnl": net,
            "r": net / pos.risk_usd if pos.risk_usd > 0 else 0.0,
            "maker_entry": pos.maker_entry, "tag": pos.tag,
        })
        st.n_trades += 1
        st.consec_losses = st.consec_losses + 1 if net < 0 else 0
        del st.positions[pos.symbol]
        self._ev(t, pos.symbol, "exit", reason=reason, price=price, pnl=net)

    # ------------------------------------------------------------------- run
    def run(self, feed: Feed, i0: int = 0, i1: int | None = None, close_at_end: bool = False) -> None:
        i1 = feed.n if i1 is None else i1
        if self.equity_curve is None or len(self.equity_curve) != feed.n:
            self.equity_curve = np.full(feed.n, np.nan)
            self.gross_curve = np.zeros(feed.n)
        st = self.state
        events, day_id, times = feed.events, feed.day_id, feed.times
        for i in range(i0, i1):
            day = int(day_id[i])
            if day != st.day:
                st.day = day
                st.day_start_equity = st.equity
                if st.halted and not self.risk.halt_sticky and day > st.halt_day:
                    st.halted, st.halt_reason, st.consec_losses = False, "", 0
            if not st.positions and not st.orders and i not in events:
                self.equity_curve[i] = st.equity
                st.last_time = times[i]
                continue
            self._step(feed, i, times[i], day)
        if close_at_end and st.positions:
            i = i1 - 1
            for pos in list(st.positions.values()):
                f = feed.sym[pos.symbol]
                px = _adverse(pos.last_price, -pos.side, f.slip_bps[i] * self.costs.slip_mult)
                self._close(pos, px, times[i], "end_of_data", maker=False)
            st.equity = st.cash
            self.equity_curve[i] = st.equity

    def _step(self, feed: Feed, i: int, t: str, day: int) -> None:
        st, c, r = self.state, self.costs, self.risk

        # a. exits flagged on an earlier bar fill at this bar's open -----------
        for pos in list(st.positions.values()):
            f = feed.sym[pos.symbol]
            if not f.valid[i]:
                # the market stopped printing bars (delisted): close at the last price, hit hard
                px = _adverse(pos.last_price, -pos.side, f.slip_bps[i] * c.slip_mult * c.stop_slip_mult * 5)
                self._close(pos, px, t, "delisted", maker=False)
                continue
            if pos.exit_pending:
                px = _adverse(f.o[i], -pos.side, f.slip_bps[i] * c.slip_mult)
                self._close(pos, px, t, pos.exit_pending, maker=False)

        # b. pending entry orders --------------------------------------------
        for sym in list(st.orders):
            od = st.orders[sym]
            f = feed.sym[sym]
            if st.halted or not f.valid[i]:
                del st.orders[sym]
                self._ev(t, sym, "order_cancelled", reason="halted" if st.halted else "no bar")
                continue
            o, h, l = f.o[i], f.h[i], f.l[i]
            slip = f.slip_bps[i] * c.slip_mult
            px, maker = None, False
            if math.isnan(od.limit):
                px = _adverse(o, od.side, slip)
            elif od.side > 0:
                if o <= od.limit:
                    px = min(od.limit, _adverse(o, 1, slip))
                elif l < od.limit * (1 - c.limit_through_bps / 1e4):
                    px, maker = od.limit, True
            else:
                if o >= od.limit:
                    px = max(od.limit, _adverse(o, -1, slip))
                elif h > od.limit * (1 + c.limit_through_bps / 1e4):
                    px, maker = od.limit, True
            if px is None:
                od.valid_left -= 1
                if od.valid_left <= 0:
                    del st.orders[sym]
                    self._ev(t, sym, "order_expired", limit=od.limit)
                continue
            del st.orders[sym]
            dist = (px - od.stop) * od.side
            if not dist > 0 or dist / px < r.min_stop_pct or dist / px > r.max_stop_pct:
                self._ev(t, sym, "order_rejected", reason="stop distance invalid at fill", price=px, stop=od.stop)
                continue
            if len(st.positions) >= r.max_positions:
                self._ev(t, sym, "order_rejected", reason="max positions")
                continue
            base = self._base_equity()
            risk_usd = base * r.risk_per_trade
            qty = risk_usd / dist
            qty = min(qty, r.max_pos_mult * base / px)
            room = r.max_gross_mult * base - self._gross()
            qty = min(qty, max(0.0, room) / px)
            if qty * px < r.min_notional:
                self._ev(t, sym, "order_rejected", reason="exposure cap / size too small")
                continue
            fee = qty * px * (c.maker_fee if maker else c.taker_fee) * c.fee_mult
            st.cash -= fee
            st.positions[sym] = Position(
                symbol=sym, side=od.side, qty=qty, entry_price=px, entry_time=t, stop=od.stop,
                stop0=od.stop, tp=od.tp, risk_usd=qty * dist, maker_entry=maker,
                limit_entry=not math.isnan(od.limit), fees=fee, last_price=px, new=True, tag=od.tag)
            self._ev(t, sym, "entry", side=od.side, price=px, qty=qty, stop=od.stop, maker=maker)

        # c. funding + d. stops / take-profits --------------------------------
        for pos in list(st.positions.values()):
            f = feed.sym[pos.symbol]
            if not f.valid[i]:
                continue
            o, h, l, cl = f.o[i], f.h[i], f.l[i], f.c[i]
            fund = pos.side * pos.qty * o * f.funding[i] * c.funding_mult   # longs pay positive rates
            st.cash -= fund
            pos.funding += fund
            long = pos.side > 0
            hit = (l <= pos.stop) if long else (h >= pos.stop)
            if hit:
                gap = (not pos.new) and ((o <= pos.stop) if long else (o >= pos.stop))
                px = _adverse(o if gap else pos.stop, -pos.side, f.slip_bps[i] * c.slip_mult * c.stop_slip_mult)
                self._close(pos, px, t, "stop", maker=False)
                continue
            if not math.isnan(pos.tp):
                thr = c.limit_through_bps / 1e4
                if not pos.new and ((o >= pos.tp) if long else (o <= pos.tp)):
                    self._close(pos, o, t, "take_profit", maker=True)
                    continue
                touched = (h > pos.tp * (1 + thr)) if long else (l < pos.tp * (1 - thr))
                if touched and not (pos.new and pos.maker_entry):
                    self._close(pos, pos.tp, t, "take_profit", maker=True)
                    continue
            pos.last_price = cl

        # e. intents emitted at this bar's close ------------------------------
        for sym in feed.events.get(i, ()):
            f = feed.sym[sym]
            pos = st.positions.get(sym)
            if pos is not None:
                if f.exit[i] and not pos.exit_pending:
                    pos.exit_pending = "signal"
                tr = f.trail[i]
                if not math.isnan(tr):   # a trailing stop may only tighten, and never cross the market
                    if pos.side > 0 and pos.stop < tr < f.c[i]:
                        pos.stop = tr
                    elif pos.side < 0 and pos.stop > tr > f.c[i]:
                        pos.stop = tr
                continue
            sd = int(f.side[i])
            if sd == 0 or sym in st.orders:
                continue
            if st.halted:
                self._ev(t, sym, "signal_blocked", reason="guardian halt: " + st.halt_reason)
                continue
            if not f.tradable[i]:
                self._ev(t, sym, "signal_blocked", reason="not in this month's universe")
                continue
            stop = f.stop[i]
            ref = f.limit[i] if not math.isnan(f.limit[i]) else f.c[i]
            if math.isnan(stop) or not (ref - stop) * sd > 0:
                self._ev(t, sym, "signal_blocked", reason="no valid stop attached")
                continue
            st.orders[sym] = Order(symbol=sym, side=sd, limit=f.limit[i], stop=stop, tp=f.tp[i],
                                   valid_left=self.valid_bars, created=t)
            self._ev(t, sym, "order_created", side=sd, limit=f.limit[i], stop=stop, tp=f.tp[i])

        # time stop, then f. mark to market + Guardian ------------------------
        unreal = 0.0
        for pos in st.positions.values():
            pos.bars_held += 1
            pos.new = False
            if self.max_hold and pos.bars_held >= self.max_hold and not pos.exit_pending:
                pos.exit_pending = "time"
            unreal += pos.side * pos.qty * (pos.last_price - pos.entry_price)
        st.equity = st.cash + unreal
        self.equity_curve[i] = st.equity
        self.gross_curve[i] = self._gross()
        st.last_time = t
        if r.guardian and not st.halted:
            if st.day_start_equity > 0 and st.equity / st.day_start_equity - 1.0 <= -r.daily_loss_limit:
                self._halt(f"daily loss limit -{r.daily_loss_limit:.0%} hit", t, day)
            elif st.consec_losses >= r.max_consec_losses:
                self._halt(f"{st.consec_losses} losing trades in a row", t, day)
