"""The audit every strategy gets, identically. See docs/PROTOCOL.md.

Nothing here reads bars at or after VALIDATION_END: the market is loaded with
`end=VALIDATION_END`, so the sealed holdout is not even in memory.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from ..data import store
from ..data.store import BTC, DESIGN_END, VALIDATION_END
from ..engine.core import Costs, Feed, Risk, attach
from ..engine.metrics import summarize
from ..engine.runner import Market, run_feed
from . import scoring

WF_START = pd.Timestamp("2023-10-01", tz="UTC")
TRAIN_MONTHS = 18
TEST_MONTHS = 3
MAX_CELLS = 36
MIN_TRAIN_TRADES = 20
MC_PATHS = 5000


# ------------------------------------------------------------------ grid
def grid_cells(strategy) -> list[dict]:
    keys = list(strategy.grid)
    cells = [dict(strategy.params)]
    for combo in itertools.product(*(strategy.grid[k] for k in keys)):
        c = {**strategy.params, **dict(zip(keys, combo))}
        if c not in cells:
            cells.append(c)
    if len(cells) > MAX_CELLS:
        raise ValueError(f"{strategy.name}: grid has {len(cells)} cells; keep it <= {MAX_CELLS}")
    return cells


# ------------------------------------------------------------- leak test
def leak_test(strategy, data: dict[str, pd.DataFrame], n_cuts: int = 5, tail: int = 48, seed: int = 0) -> dict:
    """Truncation invariance. Cut every symbol at time T, recompute intents, and
    compare the last `tail` rows with the intents computed on the full history.
    Causal code gives identical rows; anything that peeks ahead does not."""
    rng = np.random.default_rng(seed)
    full = strategy.intents(data, dict(strategy.params))
    lo = min(df.index[0] for df in data.values())
    hi = max(df.index[-1] for df in data.values())
    span = (hi - lo).total_seconds()
    mismatches, checked, examples = 0, 0, []
    for _ in range(n_cuts):
        cut = (lo + pd.Timedelta(seconds=float(rng.uniform(0.35, 0.98)) * span)).floor("h")
        part = {s: df[df.index < cut] for s, df in data.items()}
        part = {s: df for s, df in part.items() if len(df) > 0}
        got = strategy.intents(part, dict(strategy.params))
        for s, g in got.items():
            g = g.iloc[-tail:]
            f = full[s].reindex(g.index)
            for col in ("side", "limit", "stop", "tp", "trail", "exit"):
                a = g[col].to_numpy(dtype="float64")
                b = f[col].to_numpy(dtype="float64")
                bad = ~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))
                # stop/limit/tp only matter on rows that actually signal
                if col in ("limit", "stop", "tp"):
                    bad &= (g["side"].to_numpy() != 0) | (f["side"].to_numpy(dtype="float64") != 0)
                checked += len(a)
                if bad.any():
                    mismatches += int(bad.sum())
                    if len(examples) < 5:
                        examples.append({"symbol": s, "column": col, "cut": cut.isoformat(),
                                         "at": g.index[np.nonzero(bad)[0][0]].isoformat()})
    return {"passed": mismatches == 0, "mismatches": mismatches, "values_checked": checked, "examples": examples}


# ----------------------------------------------------------- walk-forward
def folds(end: pd.Timestamp = VALIDATION_END) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    out, t = [], WF_START
    while t < end:
        t1 = min(t + pd.DateOffset(months=TEST_MONTHS), end)
        out.append((t - pd.DateOffset(months=TRAIN_MONTHS), t, t1))
        t = t1
    return out


def objective(s: dict) -> float:
    if s.get("n_trades", 0) < MIN_TRAIN_TRADES:
        return -math.inf
    return s["total_return"] / max(abs(s["max_dd"]), 0.02)


def stitch(parts: list[dict], equity0: float) -> tuple[pd.Series, pd.Series, list[dict]]:
    """Join fold results into one equity curve (each fold starts flat)."""
    eqs, gross, trades, level = [], [], [], equity0
    for p in parts:
        e = p["equity"].dropna()
        if len(e):
            eqs.append(e - equity0 + level)
            level = float(eqs[-1].iloc[-1])
            gross.append(p["gross"])
        trades += p["trades"]
    if not eqs:
        return pd.Series(dtype="float64"), pd.Series(dtype="float64"), trades
    return pd.concat(eqs), pd.concat(gross), trades


def walk_forward(strategy, feeds: list[Feed], cells: list[dict], end: pd.Timestamp, costs: Costs, risk: Risk) -> dict:
    chosen, parts = [], []
    for train0, t0, t1 in folds(end):
        best, best_obj = 0, -math.inf
        for k, feed in enumerate(feeds):
            obj = objective(run_feed(feed, strategy, train0, t0, costs, risk)["summary"])
            if obj > best_obj:
                best, best_obj = k, obj
        chosen.append({"test_start": t0.strftime("%Y-%m-%d"), "test_end": t1.strftime("%Y-%m-%d"),
                       "cell": best, "params": cells[best],
                       "train_objective": None if best_obj == -math.inf else round(best_obj, 4)})
        parts.append(run_feed(feeds[best], strategy, t0, t1, costs, risk))
    return {"chosen": chosen, "parts": parts}


def rerun_chosen(strategy, feeds: list[Feed], chosen: list[dict], costs: Costs, risk: Risk,
                 start: pd.Timestamp | None = None) -> list[dict]:
    """Same folds and same chosen parameters, different costs/risk (stress tests)."""
    out = []
    for c in chosen:
        t0, t1 = pd.Timestamp(c["test_start"], tz="UTC"), pd.Timestamp(c["test_end"], tz="UTC")
        if start is not None and t0 < start:
            continue
        out.append(run_feed(feeds[c["cell"]], strategy, t0, t1, costs, risk))
    return out


# -------------------------------------------------------------- benchmark
def buy_and_hold(market: Market, start: pd.Timestamp, end: pd.Timestamp, costs: Costs, equity0: float) -> dict:
    """Buy and hold after costs, on perpetuals (so funding is paid).

    basket: equal-weight the month's point-in-time top 10, rebalance monthly,
            pay taker fee + slippage on the turnover.
    btc:    hold BTC only.
    """
    idx = market.base.index
    idx = idx[(idx >= start) & (idx < end)]
    uni = store.universe()
    out = {}
    for label in ("basket", "btc"):
        value, vals, w_prev = equity0, [], {}
        for m, grp in pd.Series(idx, index=idx).groupby(idx.strftime("%Y-%m")):
            hours = grp.index
            members = [BTC] if label == "btc" else [s for s in uni.get(m, []) if s in market.data]
            rel, fund, slip = {}, {}, {}
            for s in members:
                d = market.data[s].reindex(hours)
                c = d["close"].ffill()
                if c.notna().sum() < 2:
                    continue
                first = c.dropna().iloc[0]
                rel[s] = (c / first).fillna(1.0)
                fund[s] = d["funding"].fillna(0.0)
                a = market.base.arrays[s]["slip_bps"]
                slip[s] = float(a[market.base.index.searchsorted(hours[0])])
            if not rel:
                vals.append(pd.Series(value, index=hours))
                continue
            w_new = {s: 1.0 / len(rel) for s in rel}
            turn = sum(abs(w_new.get(s, 0.0) - w_prev.get(s, 0.0)) for s in set(w_new) | set(w_prev))
            avg_slip = float(np.mean(list(slip.values()))) / 1e4
            value -= value * turn * (costs.taker_fee * costs.fee_mult + avg_slip * costs.slip_mult)
            leg = pd.DataFrame(rel) * (value / len(rel))                    # dollar value of each leg
            paid = (leg.shift(1).fillna(value / len(rel)) * pd.DataFrame(fund)).sum(axis=1).cumsum() * costs.funding_mult
            v = leg.sum(axis=1) - paid
            vals.append(v)
            last = leg.iloc[-1]
            w_prev = {s: float(last[s] / last.sum()) for s in rel}
            value = float(v.iloc[-1])
        eq = pd.concat(vals)
        value_end = float(eq.iloc[-1]) - float(eq.iloc[-1]) * (costs.taker_fee * costs.fee_mult)   # sell at the end
        eq.iloc[-1] = value_end
        s = summarize(eq, [], equity0)
        # buy-and-hold compounds, so express drawdown the usual way (peak to trough of value)
        s["max_dd"] = float((eq / eq.cummax() - 1.0).min())
        s["calmar"] = s["annual_return"] / abs(s["max_dd"]) if s["max_dd"] < 0 else 0.0
        out[label] = {k: s[k] for k in ("total_return", "annual_return", "sharpe", "max_dd", "calmar", "worst_month")}
    return out


# ---------------------------------------------------------------- regimes
def btc_regimes(market: Market) -> pd.DataFrame:
    """Causal daily labels from BTC only, each known at the START of the day.

    trend label : bull / bear / chop  = trailing 30-day BTC return > +10% / < -10% / between
    state label : wild if 7-day realised vol is in the top fifth of the trailing year;
                  else trending if the 7-day efficiency ratio is above its trailing-year median;
                  else ranging
    """
    c = market.data[BTC]["close"]
    d = c.resample("1D").last()
    r30 = d / d.shift(30) - 1.0
    trend = pd.Series(np.where(r30 > 0.10, "bull", np.where(r30 < -0.10, "bear", "chop")), index=d.index)
    trend[r30.isna()] = "chop"
    lr = np.log(c).diff()
    vol = lr.rolling(168, min_periods=100).std().resample("1D").last()
    er = ((c - c.shift(168)).abs() / c.diff().abs().rolling(168, min_periods=100).sum()).resample("1D").last()
    vol_hi = vol > vol.rolling(365, min_periods=90).quantile(0.8)
    er_hi = er > er.rolling(365, min_periods=90).median()
    state = pd.Series(np.where(vol_hi, "wild", np.where(er_hi, "trending", "ranging")), index=d.index)
    return pd.DataFrame({"trend": trend, "state": state}).shift(1).dropna()   # yesterday's close labels today


def by_regime(eq: pd.Series, labels: pd.Series, equity0: float) -> dict:
    daily = eq.resample("1D").last().ffill().diff().dropna()
    lab = labels.reindex(daily.index).ffill()
    out = {}
    for name, grp in daily.groupby(lab):
        days = int(len(grp))
        pct = float(grp.sum() / equity0)
        out[str(name)] = {"days": days, "pnl_pct": pct, "annualised": pct / days * 365 if days else 0.0}
    return out


# ------------------------------------------------------------ monte carlo
def monte_carlo(trades: list[dict], equity0: float, seed: int = 0) -> dict:
    """Bootstrap the realised trades (resample with replacement, same count)."""
    if len(trades) < 10:
        return {"n": len(trades), "p_value_mean_le_0": 1.0, "prob_loss": 1.0}
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.choice(pnl, size=(MC_PATHS, len(pnl)), replace=True)
    paths = draws.cumsum(axis=1)
    total = paths[:, -1] / equity0
    dd = (paths - np.maximum.accumulate(np.maximum(paths, 0.0), axis=1)).min(axis=1) / equity0
    return {
        "n": int(len(pnl)), "paths": MC_PATHS,
        "total_return_p05": float(np.percentile(total, 5)), "total_return_p50": float(np.percentile(total, 50)),
        "total_return_p95": float(np.percentile(total, 95)),
        "max_dd_p50": float(np.percentile(dd, 50)), "max_dd_p95_worst": float(np.percentile(dd, 5)),
        "prob_loss": float((total <= 0).mean()),
        "p_value_mean_le_0": float(((draws.mean(axis=1) <= 0).sum() + 1) / (MC_PATHS + 1)),
    }


# ------------------------------------------------------------------ audit
def _slim(s: dict) -> dict:
    return {k: v for k, v in s.items() if k not in ("monthly",)}


def audit(strategy, market: Market, end: pd.Timestamp = VALIDATION_END,
          costs: Costs | None = None, risk: Risk | None = None) -> dict:
    costs, risk = costs or Costs(), risk or Risk()
    eq0 = risk.equity0
    cells = grid_cells(strategy)
    intents = [strategy.intents(market.data, c) for c in cells]      # causal, so computed once per cell
    feeds = [attach(market.base, it) for it in intents]
    res: dict = {
        "name": strategy.name, "idea": strategy.idea, "cause": strategy.cause, "loser": strategy.loser,
        "regime": strategy.regime, "default_params": dict(strategy.params), "grid": strategy.grid,
        "n_cells": len(cells), "valid_bars": strategy.valid_bars, "max_hold": strategy.max_hold,
        "data_asof": store.manifest()["asof_bar_cutoff_utc"], "data_source": store.manifest()["source"],
        "window_end": end.isoformat(),
        "costs": {"taker_fee": costs.taker_fee, "maker_fee": costs.maker_fee, "stop_slip_mult": costs.stop_slip_mult},
        "risk": {"equity0": eq0, "risk_per_trade": risk.risk_per_trade, "guardian": risk.guardian},
    }
    res["leak_test"] = leak_test(strategy, market.data)

    # default parameters, no re-fitting: design window and validation window
    res["default_design"] = _slim(run_feed(feeds[0], strategy, None, DESIGN_END, costs, risk)["summary"])
    res["default_validation"] = _slim(run_feed(feeds[0], strategy, DESIGN_END, end, costs, risk)["summary"])

    # walk-forward
    wf = walk_forward(strategy, feeds, cells, end, costs, risk)
    res["wf_chosen"] = wf["chosen"]
    eq_all, gross_all, tr_all = stitch(wf["parts"], eq0)
    res["wf_all"] = _slim(summarize(eq_all, tr_all, eq0, gross_all))
    val_parts = [p for p, c in zip(wf["parts"], wf["chosen"]) if pd.Timestamp(c["test_start"], tz="UTC") >= DESIGN_END]
    eq_v, gross_v, tr_v = stitch(val_parts, eq0)
    v = summarize(eq_v, tr_v, eq0, gross_v)
    res["wf_validation"] = v
    res["wf_by_quarter"] = [
        {"quarter": c["test_start"], "ret": round(p["summary"].get("total_return", 0.0), 5),
         "trades": p["summary"].get("n_trades", 0)} for p, c in zip(wf["parts"], wf["chosen"])]

    # stress tests on the validation quarters, same chosen parameters
    def stress(c: Costs, r: Risk = risk, fs: list[Feed] = feeds) -> dict:
        e, g, t = stitch(rerun_chosen(strategy, fs, wf["chosen"], c, r, DESIGN_END), eq0)
        s = summarize(e, t, eq0, g)
        return {k: s.get(k, 0.0) for k in ("total_return", "max_dd", "sharpe", "n_trades", "avg_r")}

    from dataclasses import replace
    delayed = [attach(market.base, {s: df.shift(1) for s, df in it.items()}) for it in intents]
    res["stress"] = {
        "fees_x2": stress(replace(costs, fee_mult=2.0)),
        "slippage_x2": stress(replace(costs, slip_mult=2.0)),
        "funding_x2": stress(replace(costs, funding_mult=2.0)),
        "all_costs_x2": stress(replace(costs, fee_mult=2.0, slip_mult=2.0, funding_mult=2.0)),
        "no_costs": stress(replace(costs, fee_mult=0.0, slip_mult=0.0, funding_mult=0.0)),
        "one_bar_late": stress(costs, risk, delayed),
        "guardian_off": stress(costs, replace(risk, guardian=False)),
    }

    # nearby settings: every grid cell, fixed, on the validation window
    cell_rets = [run_feed(f, strategy, DESIGN_END, end, costs, risk)["summary"] for f in feeds]
    rets = [s.get("total_return", 0.0) for s in cell_rets]
    res["neighbourhood"] = {
        "cells": len(cells), "share_profitable": float(np.mean([r > 0 for r in rets])),
        "median_return": float(np.median(rets)), "worst_return": float(min(rets)), "best_return": float(max(rets)),
        "default_return": float(rets[0]),
        "by_cell": [{"params": {k: c[k] for k in strategy.grid}, "ret": round(r, 5), "trades": s.get("n_trades", 0)}
                    for c, r, s in zip(cells, rets, cell_rets)],
    }

    reg = btc_regimes(market)
    res["regimes_trend"] = by_regime(eq_all, reg["trend"], eq0) if len(eq_all) else {}
    res["regimes_state"] = by_regime(eq_all, reg["state"], eq0) if len(eq_all) else {}
    res["monte_carlo"] = monte_carlo(tr_v, eq0)
    res["benchmark"] = buy_and_hold(market, DESIGN_END, end, costs, eq0)
    res["benchmark_wf_all"] = buy_and_hold(market, WF_START, end, costs, eq0)
    res["scores"] = scoring.score(v, res["regimes_trend"])
    res["gates"] = scoring.gates(res)
    res["_trades_validation"] = tr_v
    res["_trades_all"] = tr_all
    res["_equity_all"] = eq_all
    return res
