"""Causal indicators. Every function here uses only the current and past bars.

Never use: shift(-n), center=True, .iloc[::-1], whole-sample mean/std/quantile,
bfill(), or anything fitted on the full series. The audit runs a truncation
test on every strategy: intents computed on data cut at time T must equal the
intents computed on the full history at T. Code that peeks ahead fails it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def std(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).std()


def zscore(x: pd.Series, n: int) -> pd.Series:
    return (x - sma(x, n)) / std(x, n)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rsi(x: pd.Series, n: int = 14) -> pd.Series:
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def donchian_high(df: pd.DataFrame, n: int) -> pd.Series:
    """Highest high of the PREVIOUS n bars (excludes the current bar)."""
    return df["high"].shift(1).rolling(n, min_periods=n).max()


def donchian_low(df: pd.DataFrame, n: int) -> pd.Series:
    return df["low"].shift(1).rolling(n, min_periods=n).min()


def bbands(x: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    m, s = sma(x, n), std(x, n)
    return m - k * s, m, m + k * s


def bb_width(x: pd.Series, n: int = 20, k: float = 2.0) -> pd.Series:
    lo, m, hi = bbands(x, n, k)
    return (hi - lo) / m


def rolling_rank(x: pd.Series, n: int) -> pd.Series:
    """Percentile (0..1) of the current value within the trailing n bars."""
    return x.rolling(n, min_periods=n).rank(pct=True)


def realized_vol(close: pd.Series, n: int) -> pd.Series:
    """Std of hourly log returns over n bars (not annualised)."""
    return np.log(close).diff().rolling(n, min_periods=n).std()


def efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    """Kaufman ER: |net move| / sum(|bar moves|). ~1 trending, ~0 choppy."""
    net = (close - close.shift(n)).abs()
    path = close.diff().abs().rolling(n, min_periods=n).sum()
    return net / path.replace(0, np.nan)


def ret(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1.0
