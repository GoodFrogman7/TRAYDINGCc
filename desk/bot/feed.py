"""Closed hourly bars for the paper bot, in the research column layout.

`KrakenSource` is the ONLY network code in the bot. It reads Kraken Futures'
public market-data API through `desk.data.kraken.KrakenFutures` (plain GET
requests, no account). Nothing here can place an order.

Bar time is the bar's OPEN time (UTC), as in the research data: bar 01:00
closes at 02:00.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data import store
from ..data.download import MAX_REL_FUNDING, build_symbol
from ..data.kraken import KrakenFutures
from ..engine.core import FeedBase, make_base
from ..engine.costs import slip_table

BTC, ETH = "PF_XBTUSD", "PF_ETHUSD"
HOUR = pd.Timedelta(hours=1)
OHLC = ["open", "high", "low", "close"]
COLUMNS = OHLC + ["volume", "bar_missing", "mark_close", "spot_close", "premium", "funding_actual", "oi", "liq_vol",
                  "ls_ratio", "buy_vol", "sell_vol", "bid_10k", "bid_100k", "ask_10k", "ask_100k",
                  "funding_is_est", "funding"]                      # the research parquet layout
FLOAT32 = ("oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "premium")   # as download.fit_funding casts them
CLOCK_PATHS = ("/derivatives/api/v3/tickers", "/derivatives/api/v3/instruments")


def utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


class _StrictClient:
    """Passes calls to the real client and remembers every failed request.
    `build_symbol` carries on after a failed analytics or funding request; the bot must not."""

    def __init__(self, client: KrakenFutures):
        self.client = client
        self.failed: list[str] = []

    def _call(self, name: str, *args, **kw):
        if self.failed:          # the symbol has already failed this tick: send nothing more for it
            raise RuntimeError("skipped: an earlier request for this symbol failed")
        try:
            return getattr(self.client, name)(*args, **kw)
        except Exception as e:
            self.failed.append(f"{name} {' '.join(str(a) for a in args[:3])}: {type(e).__name__}: {e}")
            raise

    def candles(self, *args, **kw):
        return self._call("candles", *args, **kw)

    def analytics(self, *args, **kw):
        return self._call("analytics", *args, **kw)

    def funding_history(self, *args, **kw):
        return self._call("funding_history", *args, **kw)


class KrakenSource:
    """The live source: Kraken Futures public market data. Read only."""

    def __init__(self, timeout: float = 15.0, max_retries: int = 4):
        self.client = KrakenFutures(timeout=timeout, max_retries=max_retries)

    def server_time(self) -> pd.Timestamp | None:
        """The venue's clock, from the `serverTime` field of a public v3 response."""
        for path in CLOCK_PATHS:
            try:
                return utc(self.client.get(path)["serverTime"])
            except Exception:
                continue
        return None

    def bars(self, symbol: str, start: int, asof: int) -> pd.DataFrame:
        """Hourly bars from `start` (unix seconds) up to, not including, `asof`."""
        strict = _StrictClient(self.client)
        try:
            df, _ = build_symbol(strict, symbol, asof, start)
        except Exception as e:
            raise RuntimeError(f"{symbol}: a request failed: {type(e).__name__}: {e}") from e
        if strict.failed:
            raise RuntimeError(f"{symbol}: {len(strict.failed)} request(s) failed: {strict.failed[0]}")
        if df.empty:
            raise RuntimeError(f"{symbol}: no candles in the window (empty frame)")
        return df


@dataclass
class Fetched:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    server_time: pd.Timestamp | None = None
    server_time_delay: float = 0.0     # seconds it took to get the venue clock (retries), for the skew check


def closed_asof(now: pd.Timestamp, settle_seconds: int) -> pd.Timestamp:
    """Bars with open time < the result are closed: the hour floor of (now - settle_seconds)."""
    return (utc(now) - pd.Timedelta(seconds=settle_seconds)).floor("h")


def months_between(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    """'YYYY-MM' of every month from `start` to `end`, both included."""
    first, last = utc(start), utc(end)
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def symbols_needed(universe: dict[str, list[str]], start: pd.Timestamp, asof: pd.Timestamp, held: set[str],
                   extra: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """(required, context). Required: BTC, ETH, this month's universe, every symbol with a position or an
    order, and `extra`. Context: members of an earlier month the window touches (their history feeds
    cross-sectional strategies); a failed context symbol is left out, a failed required symbol stops the tick."""
    newest = utc(asof) - HOUR                                  # the newest closed bar
    months = months_between(start, newest)
    this_month = newest.strftime("%Y-%m")
    rest = (set(universe.get(this_month, ())) | set(held) | set(extra)) - {BTC, ETH}
    required = [BTC, ETH] + sorted(rest)
    earlier = {s for m in months if m != this_month for s in universe.get(m, ())}
    return required, sorted(earlier - set(required))


def fetch(source, symbols: list[str], start: pd.Timestamp, asof: pd.Timestamp, workers: int = 8) -> Fetched:
    """`source.bars` for every symbol (one retry each); only rows with start <= bar time < asof are kept."""
    start, asof = utc(start), utc(asof)
    out = Fetched()
    asked = time.monotonic()
    try:
        st = source.server_time()
        out.server_time = None if st is None else utc(st)
    except Exception:
        out.server_time = None
    out.server_time_delay = time.monotonic() - asked
    a, b = int(start.timestamp()), int(asof.timestamp())

    def one(sym: str) -> pd.DataFrame:
        err: Exception | None = None
        for _ in range(2):
            try:
                df = source.bars(sym, a, b)
                df = df[(df.index >= start) & (df.index < asof)]
                if df.empty:
                    raise RuntimeError("no closed bars inside the window")
                return df
            except Exception as e:
                err = e
        raise err

    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return out
    with ThreadPoolExecutor(max(1, min(workers, len(symbols)))) as ex:
        futs = {s: ex.submit(one, s) for s in symbols}
        for s, f in futs.items():
            try:
                out.frames[s] = f.result()
            except Exception as e:
                out.errors[s] = f"{type(e).__name__}: {e}"
    return out


def funding_model() -> dict:
    """The fitted funding estimate (`a`, `k`) that built the research data: data/manifest.json."""
    return json.loads((store.DATA / "manifest.json").read_text())["funding_model"]


def _prepare_one(raw: pd.DataFrame, t_last: pd.Timestamp, delist_after_bars: int, a: float, k: float
                 ) -> tuple[pd.DataFrame | None, int, int]:
    """One symbol: (frame or None, gap hours, bad bars). Mostly numpy: this runs for every symbol every tick."""
    absent = [c for c in OHLC + ["volume"] if c not in raw]
    if absent:
        raise ValueError(f"frame lacks required column(s): {', '.join(absent)}")
    df = raw
    if not df.index.is_monotonic_increasing or not df.index.is_unique:
        df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index <= t_last]
    if df.empty:
        return None, 0, 0
    flagged = df["bar_missing"].fillna(True).to_numpy(dtype=bool) if "bar_missing" in df else np.zeros(len(df), bool)
    o, h, lo, c = (df[x].to_numpy(dtype="float64") for x in OHLC)
    with np.errstate(invalid="ignore"):
        invalid = (np.isnan(o) | np.isnan(h) | np.isnan(lo) | np.isnan(c)
                   | (o <= 0) | (h <= 0) | (lo <= 0) | (c <= 0) | (h < lo))
    real = ~(flagged | invalid)
    if not real.any():
        return None, 0, 0
    where = np.nonzero(real)[0]
    first, last_real = df.index[where[0]], df.index[where[-1]]
    n_bad = int((invalid & ~flagged)[where[0]:].sum())           # bad bars before the first real one are dropped
    gap = int(round((t_last - last_real) / HOUR))
    end = t_last if gap < delist_after_bars else last_real       # a delisted symbol ends at its last real bar
    idx = pd.date_range(first, end, freq="h", name="time")
    df = df.drop(columns=["bar_missing"], errors="ignore")
    if len(idx) == len(df) - where[0] and real[where[0]:].all():   # the usual case: every hour has a real bar
        cols = {name: df[name].to_numpy()[where[0]:] for name in df.columns}
        missing = np.zeros(len(idx), dtype=bool)
    else:
        ok = pd.Series(real, index=df.index).reindex(idx, fill_value=False)
        df = df.reindex(idx)
        close = df["close"].astype("float64").where(ok).ffill()  # missing bar: carry the last real close
        for name in OHLC:
            df[name] = df[name].astype("float64").where(ok, close)
        df["volume"] = df["volume"].astype("float64").where(ok, 0.0)
        cols = {name: df[name].to_numpy() for name in df.columns}
        missing = ~ok.to_numpy()
    n = len(idx)
    out: dict[str, np.ndarray] = {}
    for name in COLUMNS:
        if name == "bar_missing":
            out[name] = missing
        elif name in ("funding_is_est", "funding"):
            continue
        elif name in cols:
            out[name] = np.asarray(cols[name], dtype="float32" if name in FLOAT32 else "float64")
        else:
            out[name] = np.full(n, np.nan, dtype="float32" if name in FLOAT32 else "float64")
    # funding exactly as download.fit_funding: the venue's rate where served, else a + k * premium(previous hour)
    premium = np.asarray(cols["premium"], dtype="float64") if "premium" in cols else np.full(n, np.nan)
    est = np.clip(a + k * np.r_[np.nan, premium[:-1]], -MAX_REL_FUNDING, MAX_REL_FUNDING)
    actual = out["funding_actual"]
    out["funding_is_est"] = np.isnan(actual)
    funding = np.where(out["funding_is_est"], est, actual)
    out["funding"] = np.where(np.isnan(funding), 0.0, funding)
    for name in cols:                                            # columns the research layout does not know
        if name not in out:
            out[name] = cols[name]
    return pd.DataFrame(out, index=idx), gap, n_bad


def prepare(frames: dict[str, pd.DataFrame], t_last: pd.Timestamp, delist_after_bars: int, model: dict | None = None
            ) -> tuple[dict[str, pd.DataFrame], dict[str, int], dict[str, int]]:
    """Raw frames -> (data, gaps, bad). See docs/BOT_SPEC.md under Interfaces for the exact rules."""
    t_last = utc(t_last)
    if model is None:
        model = funding_model()
    per = model.get("per_symbol") or {}
    data: dict[str, pd.DataFrame] = {}
    gaps: dict[str, int] = {}
    bad: dict[str, int] = {}
    for s, raw in frames.items():
        fit = per.get(s) or {}
        df, gap, n_bad = _prepare_one(raw, t_last, delist_after_bars,
                                      float(fit.get("a", model["pooled_a"])), float(fit.get("k", model["pooled_k"])))
        if df is None:
            continue
        data[s] = df
        if gap > 0:
            gaps[s] = gap
        if n_bad:
            bad[s] = n_bad
    return data, gaps, bad


def build_base(data: dict[str, pd.DataFrame], t_cap: pd.Timestamp) -> FeedBase:
    """Prices, funding, slippage and universe membership up to and including bar `t_cap`,
    built the same way as `desk.engine.runner.load_market`."""
    tradable = {s: store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool) for s, df in data.items()}
    return make_base(data, tradable=tradable, slip_bps=slip_table(data), end=utc(t_cap) + HOUR)
