"""Slippage model built from the venue's own order-book analytics.

Kraken publishes, per hour, the price a $10k market order would have executed
at on each side (`bid_10k`, `ask_10k`). Half of that round-trip gap is the
one-way cost of crossing the book with ~$10k, which matches this account's
position size.

  slip_bps[t] = rolling 7-day median of half-gap, lagged one bar, floored/capped

That history starts around 2023-06. Before then the series is a fixed ESTIMATE
that uses no later data: MAJOR_BPS for BTC and ETH, DEFAULT_BPS for everything
else. Symbols with no measurements at all use the same constants. Stops are
charged a multiple of this (see Costs.stop_slip_mult).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FLOOR_BPS = 0.5
CAP_BPS = 60.0
DEFAULT_BPS = 8.0
MAJOR_BPS = 2.0
MAJORS = ("PF_XBTUSD", "PF_ETHUSD")


def slip_series(df: pd.DataFrame, symbol: str = "") -> pd.Series:
    early = MAJOR_BPS if symbol in MAJORS else DEFAULT_BPS
    if "bid_10k" not in df or df["bid_10k"].notna().sum() < 24 * 30:
        return pd.Series(early, index=df.index)
    mid = (df["ask_10k"] + df["bid_10k"]) / 2
    half = ((df["ask_10k"] - df["bid_10k"]) / mid / 2 * 1e4).where(lambda s: s >= 0)
    med = half.rolling(168, min_periods=24).median().shift(1)      # trailing week, known before the bar
    out = med.ffill()                                               # gaps: carry the last measured value
    out = out.fillna(early)                                         # before any measurement: fixed estimate
    return out.clip(FLOOR_BPS, CAP_BPS)


def slip_table(data: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    return {s: slip_series(df, s) for s, df in data.items()}
