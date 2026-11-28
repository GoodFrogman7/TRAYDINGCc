"""Load the research dataset and enforce the research windows.

The three windows are fixed BEFORE any strategy is looked at:

  DESIGN      first bar .. 2024-12-31   ideas are explored and parameters chosen here
  VALIDATION  2025-01-01 .. 2026-05-17  never seen while designing; used to rank
  HOLDOUT     2026-05-18 .. last bar    sealed; only the finalists touch it, once

`load_design()` is the only loader idea-generation code may use.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
H1 = DATA / "kraken_futures" / "1h"

DESIGN_END = pd.Timestamp("2025-01-01", tz="UTC")       # exclusive
VALIDATION_END = pd.Timestamp("2026-05-18", tz="UTC")   # exclusive
BTC = "PF_XBTUSD"


@lru_cache(maxsize=None)
def manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text())


@lru_cache(maxsize=None)
def universe() -> dict[str, list[str]]:
    """{'YYYY-MM': [top-10 symbols for that month]} ranked on the PRIOR 30 days."""
    return json.loads((DATA / "universe.json").read_text())["months"]


def symbols() -> list[str]:
    return sorted(p.stem for p in H1.glob("*.parquet"))


@lru_cache(maxsize=None)
def _read(symbol: str) -> pd.DataFrame:
    return pd.read_parquet(H1 / f"{symbol}.parquet")


_CEILING: pd.Timestamp | None = None


@contextmanager
def ceiling(ts: pd.Timestamp | None):
    """While active, no loader returns bars at or after `ts`. The audit sets this
    to the end of VALIDATION (so the sealed holdout cannot be read by any
    strategy, even one that loads data itself) and the look-ahead test sets it to
    each truncation point."""
    global _CEILING
    prev = _CEILING
    _CEILING = prev if ts is None else (ts if prev is None else min(ts, prev))   # can only tighten
    try:
        yield
    finally:
        _CEILING = prev


def load(symbol: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """One symbol's hourly bars. `end` is exclusive. Returns a copy."""
    df = _read(symbol)
    if _CEILING is not None:
        end = _CEILING if end is None else min(end, _CEILING)
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index < end]
    return df.copy()


def load_all(start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
             syms: list[str] | None = None) -> dict[str, pd.DataFrame]:
    out = {}
    for s in syms or symbols():
        df = load(s, start, end)
        if len(df):
            out[s] = df
    return out


def load_design(syms: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Design window only. Idea generation must not see anything later."""
    return load_all(end=DESIGN_END, syms=syms)


def tradable_mask(symbol: str, index: pd.DatetimeIndex) -> pd.Series:
    """True on bars where `symbol` is in that month's point-in-time top-10."""
    uni = universe()
    months = index.strftime("%Y-%m")
    return pd.Series([symbol in uni.get(m, ()) for m in months], index=index, dtype=bool)
