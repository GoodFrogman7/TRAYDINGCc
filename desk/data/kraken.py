"""Kraken Futures public market-data client (no account, no keys).

Every endpoint used here is unauthenticated. Timestamps returned by the charts
and analytics endpoints are BAR OPEN times (verified 2026-11-18: the hourly
`trade-volume` analytic matches the hourly trade candle volume at offset 0).

Source: https://futures.kraken.com  (charts API v1, derivatives API v3/v4)
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd
import requests

BASE = "https://futures.kraken.com"
RES_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
MAX_ROWS = 2000  # both charts and analytics return at most 2000 rows per call

# Categories that are not crypto markets (tokenised stocks, FX, metals, ...).
NON_CRYPTO_CATEGORIES = {
    "xStocks", "Equities", "Commodities", "Stablecoin", "Pre-IPO", "Forex",
    "Indices", "Real-world assets",
}


class KrakenFutures:
    def __init__(self, timeout: float = 40.0, max_retries: int = 7, min_gap: float = 0.05):
        self._local = threading.local()
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_gap = min_gap
        self._lock = threading.Lock()
        self._last = 0.0
        self.calls = 0

    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = "desk-research/0.1"
            self._local.s = s
        return s

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = BASE + path
        err: Exception | None = None
        for attempt in range(self.max_retries):
            with self._lock:
                wait = self.min_gap - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
                self.calls += 1
            try:
                r = self._session().get(url, params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (404, 400):
                    raise KeyError(f"{r.status_code} {url} {params}: {r.text[:200]}")
                err = RuntimeError(f"HTTP {r.status_code} {url}: {r.text[:200]}")
            except KeyError:
                raise
            except Exception as e:  # network errors, JSON errors
                err = e
            time.sleep(min(30.0, 0.5 * 2 ** attempt))
        raise RuntimeError(f"gave up on {url} {params}: {err}")

    # ---- reference data -------------------------------------------------
    def instruments(self) -> list[dict]:
        return self.get("/derivatives/api/v3/instruments")["instruments"]

    def tickers(self) -> list[dict]:
        return self.get("/derivatives/api/v3/tickers")["tickers"]

    def chart_symbols(self, tick_type: str = "trade", polls: int = 8) -> list[str]:
        """All symbols the charts API knows, INCLUDING delisted contracts.

        The endpoint is inconsistent between calls (observed 2026-11-18: 503 PF_
        symbols on one call, 287 on the next, the difference being delisted
        contracts), so we poll it several times and take the union.
        """
        seen: set[str] = set()
        for i in range(polls):
            seen.update(self.get(f"/api/charts/v1/{tick_type}"))
            time.sleep(0.4)
        return sorted(seen)

    # ---- candles ----------------------------------------------------------
    def candles(self, symbol: str, tick_type: str, resolution: str, start: int, end: int,
                retry_empty: int = 2) -> pd.DataFrame:
        """OHLCV candles in [start, end) (unix seconds). Index = bar open time, UTC.

        tick_type: 'trade' (last traded), 'mark' (mark price), 'spot' (index).
        """
        res = RES_SECONDS[resolution]
        start = (start // res) * res
        rows: list[dict] = []
        a = start
        while a < end:
            b = min(end, a + MAX_ROWS * res)
            d = self.get(f"/api/charts/v1/{tick_type}/{symbol}/{resolution}", {"from": a, "to": b - 1})
            cs = d.get("candles") or []
            for _ in range(retry_empty if not cs else 0):   # an empty page can be a transient miss
                time.sleep(0.7)
                d = self.get(f"/api/charts/v1/{tick_type}/{symbol}/{resolution}", {"from": a, "to": b - 1})
                cs = d.get("candles") or []
                if cs:
                    break
            rows.extend(cs)
            if d.get("more_candles") and cs:
                a = cs[-1]["time"] // 1000 + res
            else:
                a = b
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype="float64")
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.drop_duplicates("time").set_index("time").sort_index()
        return df[["open", "high", "low", "close", "volume"]].astype("float64")

    # ---- analytics --------------------------------------------------------
    def analytics(self, symbol: str, kind: str, start: int, end: int, interval: int = 3600) -> pd.DataFrame:
        """Hourly analytics series in [start, end). Index = bar open time, UTC.

        The endpoint returns an empty page (with more=true) for windows before
        its history begins, so we always walk fixed windows instead of trusting
        the `more` flag.
        """
        start = (start // interval) * interval
        frames: list[pd.DataFrame] = []
        a = start
        while a < end:
            b = min(end, a + MAX_ROWS * interval)
            d = self.get(f"/api/charts/v1/analytics/{symbol}/{kind}", {"since": a, "to": b - 1, "interval": interval})
            res = d.get("result") or {}
            ts = res.get("timestamp") or []
            if ts:
                frames.append(_analytics_frame(kind, ts, res.get("data")))
                last = int(ts[-1])
                a = last + interval if (res.get("more") and last + interval < b) else b
            else:
                a = b
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames)
        return df[~df.index.duplicated()].sort_index()

    # ---- funding ----------------------------------------------------------
    def funding_history(self, symbol: str) -> pd.DataFrame:
        """Actual hourly funding rates. The endpoint only serves about the last
        year. A rate stamped T applies to the hour [T, T+1h) and is derived from
        the premium during the previous hour (verified by lag correlation).
        """
        d = self.get("/derivatives/api/v4/historicalfundingrates", {"symbol": symbol})
        r = d.get("rates") or []
        if not r:
            return pd.DataFrame(columns=["funding_rel"], dtype="float64")
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.drop_duplicates("time").set_index("time").sort_index()
        return df[["relativeFundingRate"]].rename(columns={"relativeFundingRate": "funding_rel"}).astype("float64")


def _analytics_frame(kind: str, ts: list, data: Any) -> pd.DataFrame:
    idx = pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s", utc=True)
    out: dict[str, list] = {}
    if kind == "open-interest":            # list of [open, high, low, close]
        out["oi"] = [float(x[3]) for x in data]
    elif kind == "liquidation-volume":     # base units liquidated in the hour
        out["liq_vol"] = [float(x) for x in data]
    elif kind == "long-short-ratio":       # share of accounts net long (0..1)
        out["ls_ratio"] = [float(x) for x in data]
    elif kind == "cvd":                    # aggressor buy / sell volume
        out["buy_vol"] = [float(x) for x in data["buy_volume"]]
        out["sell_vol"] = [float(x) for x in data["sell_volume"]]
    elif kind == "slippage":               # executable price for a given USD size
        for side in ("bid", "ask"):
            for size in ("10k", "100k"):
                vals = (data.get(side) or {}).get(f"slippage_{size}") or []
                out[f"{side}_{size}"] = [float(x) if x not in (None, "") else float("nan") for x in vals]
    else:
        raise ValueError(f"unsupported analytics kind {kind}")
    n = len(idx)
    out = {k: (v + [float("nan")] * (n - len(v)))[:n] for k, v in out.items()}
    df = pd.DataFrame(out, index=pd.DatetimeIndex(idx, name="time"))
    return df
