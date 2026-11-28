"""Shared test doubles for the paper-bot tests: a fake market-data source, a tiny
synthetic market with its own universe and manifest, and the socket block.

Nothing here touches the network or the real `data/` and `state/` directories.
"""
from __future__ import annotations

import json
import re
import socket
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

from desk.data import kraken, store

BTC, ETH = "PF_XBTUSD", "PF_ETHUSD"
ALTS = ("PF_AAAUSD", "PF_BBBUSD", "PF_CCCUSD")
SYMBOLS = (BTC, ETH) + ALTS
HOUR = pd.Timedelta(hours=1)
FIRST_BAR = pd.Timestamp("2026-07-01", tz="UTC")
N_BARS = 3400                                   # through 2026-11-19 15:00
MONTHS = ("2026-07", "2026-08", "2026-09", "2026-10", "2026-11")
WINDOW = 300                                    # feed.window_bars in the ordinary test installation
FULL_WINDOW = 900                               # ... and where the measured slippage table must match
PARAMS = {"n": 24, "atr_n": 12, "stop_atr": 2.0}     # ref_donchian, tuned only to trade often


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to open a socket fails the test."""
    def refuse(*a, **k):
        raise AssertionError("a paper-bot test tried to open a network socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def make_frames(seed: int = 3, n: int = N_BARS, depth: bool = True) -> dict[str, pd.DataFrame]:
    """Random-walk hourly bars in the layout `download.build_symbol` returns
    (research columns without `funding` / `funding_is_est`). `depth=False` leaves the order-book
    columns empty, so slippage is the engine's fixed estimate and short windows are enough."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(FIRST_BAR, periods=n, freq="h", name="time")
    out = {}
    for k, s in enumerate(SYMBOLS):
        ret = rng.normal(0.0, 0.006 + 0.002 * k, n)
        close = (100.0 * (k + 1)) * np.exp(np.cumsum(ret))
        op = np.r_[close[0], close[:-1]]
        wick = np.abs(rng.normal(0.0, 0.002, (2, n)))
        hi = np.maximum(op, close) * (1 + wick[0])
        lo = np.minimum(op, close) * (1 - wick[1])
        half = close * (2 + k) / 1e4
        prem = rng.normal(0.0, 2e-4, n)
        df = pd.DataFrame({
            "open": op, "high": hi, "low": lo, "close": close,
            "volume": rng.uniform(10, 100, n), "bar_missing": False,
            "mark_close": close * (1 + prem), "spot_close": close,
            "premium": prem, "funding_actual": prem / 24.0,
            "oi": rng.uniform(1e3, 2e3, n), "liq_vol": rng.uniform(0, 5, n),
            "ls_ratio": rng.uniform(0.3, 0.7, n),
            "buy_vol": rng.uniform(5, 50, n), "sell_vol": rng.uniform(5, 50, n),
            "bid_10k": close - half, "bid_100k": close - 3 * half,
            "ask_10k": close + half, "ask_100k": close + 3 * half,
        }, index=idx)
        if not depth:
            df[["bid_10k", "bid_100k", "ask_10k", "ask_100k"]] = np.nan
        out[s] = df
    return out


class FakeSource:
    """Stands in for `feed.KrakenSource`: serves closed AND still-open bars, like the venue."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames
        self.now: pd.Timestamp | None = None     # what `server_time` answers (None = same as the tick clock)
        self.skew = pd.Timedelta(0)
        self.fail: set[str] = set()              # symbols whose request fails
        self.last_bar: dict[str, pd.Timestamp] = {}   # symbol -> newest bar the venue serves
        self.calls: list[tuple[str, int, int]] = []

    def server_time(self):
        return None if self.now is None else self.now + self.skew

    def bars(self, symbol: str, start: int, asof: int) -> pd.DataFrame:
        self.calls.append((symbol, start, asof))
        if symbol in self.fail:
            raise RuntimeError(f"fake outage for {symbol}")
        df = self.frames[symbol]
        lo = pd.Timestamp(start, unit="s", tz="UTC")
        hi = pd.Timestamp(asof, unit="s", tz="UTC") + HOUR       # includes the bar that is still open
        df = df[(df.index >= lo) & (df.index < hi)]
        if symbol in self.last_bar:
            df = df[df.index <= self.last_bar[symbol]]
        if df.empty:
            raise RuntimeError(f"no candles for {symbol}")
        return df.copy()


class FakeVenue:
    """Answers the public HTTP endpoints `KrakenFutures` calls, from frames, and records every request.
    Installed over `requests.Session.request`, so the real client and `feed.KrakenSource` run unchanged."""

    def __init__(self, frames: dict[str, pd.DataFrame], server_time: str = "2026-07-05T00:07:00.123Z"):
        self.frames = frames
        self.server_time = server_time
        self.requests: list[dict] = []
        self.fail_paths: tuple[str, ...] = ()
        self.empty = False

    def install(self, monkeypatch):
        venue = self

        def request(session, method, url, **kw):
            venue.requests.append({"method": method, "url": url, "params": kw.get("params") or {},
                                   "headers": dict(session.headers), "kw": sorted(kw)})
            return venue.respond(url, kw.get("params") or {})
        monkeypatch.setattr(requests.Session, "request", request)
        monkeypatch.setattr(kraken.time, "sleep", lambda s: None)

    def respond(self, url, params):
        path = url.replace(kraken.BASE, "")
        body, status = self.body(path, params), 200
        if any(p in path for p in self.fail_paths):
            body, status = {"error": "boom"}, 500

        class Response:
            status_code = status
            text = json.dumps(body)[:200]

            def json(self):
                return body
        return Response()

    def rows(self, symbol: str, lo: int, hi: int) -> pd.DataFrame:
        f = self.frames[symbol]
        sec = np.array([int(t.timestamp()) for t in f.index])
        return f[(sec >= lo) & (sec <= hi)]

    def body(self, path, params):
        if path.startswith("/derivatives/api/v3/"):
            return {"result": "success", "serverTime": self.server_time, "tickers": [], "instruments": []}
        if path.startswith("/derivatives/api/v4/historicalfundingrates"):
            f = self.frames[params["symbol"]]
            return {"rates": [] if self.empty else [
                {"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "fundingRate": 1.0, "relativeFundingRate": float(v)}
                for t, v in f["funding_actual"].items()]}
        m = re.fullmatch(r"/api/charts/v1/analytics/([A-Z_]+)/([a-z-]+)", path)
        if m:
            f = self.rows(m.group(1), params["since"], params["to"])
            stamps = [int(t.timestamp()) for t in f.index]
            data = {"open-interest": [[0, 0, 0, float(v)] for v in f["oi"]],
                    "liquidation-volume": [float(v) for v in f["liq_vol"]],
                    "long-short-ratio": [float(v) for v in f["ls_ratio"]],
                    "cvd": {"buy_volume": [float(v) for v in f["buy_vol"]],
                            "sell_volume": [float(v) for v in f["sell_vol"]]},
                    "slippage": {side: {f"slippage_{size}": [float(v) for v in f[f"{side}_{size}"]]
                                        for size in ("10k", "100k")} for side in ("bid", "ask")}}[m.group(2)]
            return {"result": {"timestamp": stamps, "data": data, "more": False}}
        m = re.fullmatch(r"/api/charts/v1/(trade|mark|spot)/([A-Z_]+)/1h", path)
        assert m, f"unexpected request {path}"
        tick = m.group(1)
        f = self.rows(m.group(2), params["from"], params["to"])
        out = []
        for t, r in (f.iloc[:0] if self.empty else f).iterrows():
            c = {"trade": r["close"], "mark": r["mark_close"], "spot": r["spot_close"]}[tick]
            o, h, lo = (r["open"], r["high"], r["low"]) if tick == "trade" else (c, c, c)
            out.append({"time": int(t.timestamp()) * 1000, "open": str(o), "high": str(h), "low": str(lo),
                        "close": str(c), "volume": str(r["volume"])})
        return {"candles": out, "more_candles": False}


class World:
    """One temporary bot installation: config file, state directory, data directory, fake source."""

    def __init__(self, tmp_path: Path, depth: bool = False, window: int = WINDOW):
        self.root = tmp_path
        self.window = window
        self.state = tmp_path / "state"
        self.data = tmp_path / "data"
        self.config = tmp_path / "bot.yaml"
        self.data.mkdir()
        self.frames = make_frames(depth=depth)
        self.source = FakeSource(self.frames)
        self.write_universe(MONTHS)
        (self.data / "manifest.json").write_text(json.dumps(
            {"funding_model": {"pooled_a": 0.0, "pooled_k": 1.0 / 24.0, "per_symbol": {}}}))
        self.write_config()

    def write_universe(self, months, members=None) -> None:
        """`months`: a list of 'YYYY-MM' (all with the same members) or a ready {month: [symbols]} mapping."""
        if not isinstance(months, dict):
            members = list(members) if members is not None else list(SYMBOLS)
            months = {m: members for m in months}
        (self.data / "universe.json").write_text(json.dumps({"months": months}))
        store.universe.cache_clear()

    def write_config(self, champion="default", challengers=(), kill=False, feed=None, **sections) -> None:
        """Write the config file (JSON is valid YAML). `sections` adds e.g. account={...} or guardian={...}."""
        if champion == "default":
            champion = {"strategy": "desk.strategies.ref_donchian", "params": PARAMS}
        doc = {"mode": "paper", "kill": kill, "champion": champion, "challengers": list(challengers),
               "feed": {"window_bars": self.window, **(feed or {})}, **sections}
        self.config.write_text(json.dumps(doc, indent=1))

    def tick(self, bar: pd.Timestamp, minutes: float = 7.0) -> dict:
        """Run the tick that would fire `minutes` after `bar` closed."""
        from desk.bot import paper
        now = bar + HOUR + pd.Timedelta(minutes=minutes)
        self.source.now = now                    # the venue's clock agrees with ours (plus `source.skew`)
        return paper.tick(self.config, self.state, now=now, source=self.source)

    def bar(self, k: int) -> pd.Timestamp:
        return FIRST_BAR + k * HOUR

    def book(self, name: str = "champion") -> dict:
        return json.loads((self.state / f"{name}.json").read_text())

    def alerts(self, code: str | None = None) -> list[dict]:
        rows = read_jsonl(self.state / "alerts.jsonl")
        return [r for r in rows if code is None or r["code"] == code]


def _installed(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(store, "DATA", tmp_path / "data")
    store.universe.cache_clear()
    return World(tmp_path, **kw)


@pytest.fixture
def world(tmp_path, monkeypatch, no_network):
    """A fresh installation whose universe and manifest live under tmp_path (fixed slippage, 300-bar window)."""
    yield _installed(tmp_path, monkeypatch)
    store.universe.cache_clear()            # the next reader must see the real file again


@pytest.fixture
def full_world(tmp_path, monkeypatch, no_network):
    """The same with order-book depth in the bars (slippage measured from it) and a 900-bar window."""
    yield _installed(tmp_path, monkeypatch, depth=True, window=FULL_WINDOW)
    store.universe.cache_clear()


def fake_strategy_module(monkeypatch, name: str, strategy) -> str:
    """Register `strategy` as desk.strategies.<name> for one test (no file is written)."""
    full = f"desk.strategies.{name}"
    mod = types.ModuleType(full)
    mod.STRATEGY = strategy
    monkeypatch.setitem(sys.modules, full, mod)
    return full


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
