"""Small helpers shared by strategy modules. Everything here is causal."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import ta
from .base import blank_intents

BTC = "PF_XBTUSD"
ETH = "PF_ETHUSD"


def entries(df: pd.DataFrame, long: pd.Series | None, short: pd.Series | None, stop_dist: pd.Series) -> pd.DataFrame:
    """Market entries at the next open with a stop `stop_dist` away from the signal close."""
    it = blank_intents(df.index)
    ok = stop_dist.notna() & (stop_dist > 0)
    side = np.zeros(len(df), dtype=np.int8)
    if long is not None:
        side[(long.fillna(False) & ok).to_numpy(dtype=bool)] = 1
    if short is not None:
        side[(short.fillna(False) & ok).to_numpy(dtype=bool)] = -1
    it["side"] = side
    c = df["close"].to_numpy()
    d = stop_dist.to_numpy(dtype="float64")
    it["stop"] = np.where(side > 0, c - d, np.where(side < 0, c + d, np.nan))
    return it


def mark_sigma(df: pd.DataFrame, n: int = 168) -> tuple[pd.Series, pd.Series]:
    """Hourly log returns of the mark price and their trailing std, known before the bar."""
    lr = np.log(df["mark_close"]).diff()
    return lr, lr.rolling(n).std().shift(1)


def print_ok(df: pd.DataFrame, tol: float = 0.003) -> pd.Series:
    """The last traded price agrees with the mark (the next open is that last print)."""
    return (df["close"] / df["mark_close"] - 1.0).abs() <= tol


def is_weekly_bar(index: pd.DatetimeIndex, dow: int, hour: int) -> np.ndarray:
    return (index.dayofweek == dow) & (index.hour == hour)


def daily_vol(close: pd.Series) -> pd.Series:
    """One-day volatility estimate from the trailing week of hourly log returns."""
    return ta.realized_vol(close, 168) * np.sqrt(24)


def month_code(index: pd.DatetimeIndex) -> np.ndarray:
    """YYYYMM as an integer per bar (fast alternative to strftime)."""
    return (index.year * 100 + index.month).to_numpy()


def months_where(universe: dict[str, list[str]], pick) -> dict[str, np.ndarray]:
    """{symbol: array of YYYYMM codes in which pick(month_list) contains the symbol}."""
    out: dict[str, list[int]] = {}
    for m, syms in universe.items():
        for s_ in pick(syms):
            out.setdefault(s_, []).append(int(m.replace("-", "")))
    return {k: np.array(v) for k, v in out.items()}
