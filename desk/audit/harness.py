"""The audit every strategy gets, identically. See docs/PROTOCOL.md.

Nothing here reads bars at or after VALIDATION_END: the market is loaded with
`end=VALIDATION_END`, so the sealed holdout is not even in memory.
"""
from __future__ import annotations

import importlib
import inspect
import itertools
import math
import sys
from dataclasses import replace

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
TARGETED_DEFAULT_CELL = 300     # truncation probes placed right after rows that act, default parameters
TARGETED_OTHER_CELLS = 8        # per non-default grid cell
RANDOM_CUTS = 4
FORBIDDEN_IN_STRATEGY = ("read_parquet", "read_csv", "store.load", "store._read", "load_all", "load_design",
                         "open(", "requests.", "urllib", "shift(-", "center=True", "bfill(")


def source_scan(strategy) -> list[str]:
    """Static check: a strategy must be a function of its argument only."""
    mod = sys.modules.get(type(strategy).__module__)
    if mod is None or not mod.__name__.startswith("desk.strategies.s_"):
        return []
    try:
        src = inspect.getsource(mod)
    except (OSError, TypeError):
        return []
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    return [tok for tok in FORBIDDEN_IN_STRATEGY if tok in code]


def fresh_instance(strategy):
    """A brand-new strategy object, so no cache from an earlier call can answer for it."""
    mod = sys.modules.get(type(strategy).__module__)
    if mod is not None and mod.__name__.startswith("desk.strategies.s_") and getattr(mod, "STRATEGY", None) is not None:
        return importlib.reload(mod).STRATEGY
    try:
        return type(strategy)()
    except Exception:
        return strategy


def _acting_times(full: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    out: set = set()
    for f in full.values():
        m = (f["side"].to_numpy(dtype="float64") != 0) | f["exit"].to_numpy(dtype=bool) | f["trail"].notna().to_numpy()
        out.update(f.index[m])
    return sorted(out)


def _diff(g: pd.DataFrame, f: pd.DataFrame) -> int:
    """Number of values in `g` (truncated run) that differ from `f` (full run) on g's rows."""
    f = f.reindex(g.index)
    acting = (np.nan_to_num(g["side"].to_numpy(dtype="float64")) != 0) | \
             (np.nan_to_num(f["side"].to_numpy(dtype="float64")) != 0)
    n = 0
    for col in ("side", "limit", "stop", "tp", "trail", "exit"):
        a, b = g[col].to_numpy(dtype="float64"), f[col].to_numpy(dtype="float64")
        bad = ~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))
        if col in ("limit", "stop", "tp"):      # prices only matter on rows that open a trade
            bad &= acting
        n += int(bad.sum())
    return n


def _probe(strategy, data: dict[str, pd.DataFrame], cell: dict, cut: pd.Timestamp,
           full: dict[str, pd.DataFrame]) -> tuple[int, str]:
    """Recompute intents on data cut at `cut` (fresh object, store ceiling at `cut`)
    and count values that differ from the full-history run."""
    part = {s: df[df.index < cut] for s, df in data.items()}
    part = {s: df for s, df in part.items() if len(df)}
    if not part:
        return 0, ""
    with store.ceiling(cut):
        got = fresh_instance(strategy).intents(part, dict(cell))
    for s, g in got.items():
        d = _diff(g, full[s])
        if d:
            return d, s
    return 0, ""


def leak_test(strategy, data: dict[str, pd.DataFrame], full_by_cell: list[dict] | None = None,
              n_targeted: int = TARGETED_DEFAULT_CELL, n_other: int = TARGETED_OTHER_CELLS,
              n_random: int = RANDOM_CUTS, seed: int = 0, extra_cuts: list[pd.Timestamp] | None = None) -> dict:
    """Truncation invariance: for a causal strategy, intents computed on data cut at
    time T equal the intents computed on the full history for every row before T.

    * EVERY grid cell is probed, not only the defaults (the walk-forward may trade any).
    * Cuts are placed right AFTER rows that act (entry / exit / trail), sampled over
      the whole history, because a one-bar peek only shows on the row just before a
      cut; plus a few random cuts.
    * Every row of the truncated output is compared.
    * Each probe runs on a fresh strategy object with the data store capped at the
      cut, so neither a cache nor a direct file read can answer for the future.
    * `full_by_cell` are the intents the audit actually trades.

    300 targeted probes in the default cell miss a leak that drives 3% of signals
    with probability 0.97^300 (about 1 in 9,000). `leak_replay` then replays every
    reported trade for strategies that pass the other gates.
    """
    rng = np.random.default_rng(seed)
    cells = grid_cells(strategy)
    lo = min(df.index[0] for df in data.values())
    hi = max(df.index[-1] for df in data.values())
    bad_tokens = source_scan(strategy)
    out = {"passed": True, "mismatches": 0, "probes": 0, "cells": len(cells), "examples": [],
           "forbidden_code": bad_tokens}
    for k, cell in enumerate(cells):
        if full_by_cell is not None:
            full = full_by_cell[k]
        else:
            with store.ceiling(hi + pd.Timedelta(hours=1)):
                full = fresh_instance(strategy).intents(data, dict(cell))
        acts = _acting_times(full)
        cuts = [(lo + (hi - lo) * float(rng.uniform(0.05, 0.99))).floor("h") for _ in range(n_random if k == 0 else 1)]
        want = n_targeted if k == 0 else n_other
        if acts:
            pick = rng.choice(len(acts), size=min(want, len(acts)), replace=False)
            cuts += [acts[int(i)] + pd.Timedelta(hours=1) for i in pick]
        if k == 0 and extra_cuts:
            cuts += list(extra_cuts)
        for cut in cuts:
            d, sym = _probe(strategy, data, cell, cut, full)
            out["probes"] += 1
            if d:
                out["mismatches"] += d
                out["examples"].append({"symbol": sym, "cut": cut.isoformat(), "params": cell})
                break                       # one proven leak is enough for this cell
        if out["mismatches"] and len(out["examples"]) >= 3:
            break
    out["passed"] = out["mismatches"] == 0 and not bad_tokens
    return out


def leak_replay(strategy, data: dict[str, pd.DataFrame], trades: list[dict], cell_for_time, cells: list[dict],
                full_by_cell: list[dict]) -> dict:
    """Exhaustive version for strategies that pass every other gate: replay the
    signal behind EVERY reported trade (a cut at each entry and each exit time)
    with the parameters that were live at that time."""
    cuts: dict[pd.Timestamp, int] = {}
    for t in trades:
        for key in ("entry_time", "exit_time"):
            ts = pd.Timestamp(t[key])
            cuts[ts] = cell_for_time(ts)
    mism, examples = 0, []
    for cut, k in sorted(cuts.items()):
        d, sym = _probe(strategy, data, cells[k], cut, full_by_cell[k])
        if d:
            mism += d
            if len(examples) < 5:
                examples.append({"symbol": sym, "cut": cut.isoformat(), "params": cells[k]})
    return {"passed": mism == 0, "mismatches": mism, "probes": len(cuts), "examples": examples}


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
                first = d["open"].dropna().iloc[0]      # the month starts at its first open, not its first close
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
        exit_slip = float(np.mean(list(slip.values()))) / 1e4 * costs.slip_mult if slip else 0.0
        eq.iloc[-1] = float(eq.iloc[-1]) * (1.0 - costs.taker_fee * costs.fee_mult - exit_slip)   # sell at the end
        s = summarize(eq, [], equity0)
        # buy-and-hold compounds, so express drawdown the usual way (peak to trough of value)
        s["max_dd"] = float((eq / eq.cummax().clip(lower=equity0) - 1.0).min())
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
    last = eq.resample("1D").last().ffill()
    daily = last.diff()
    daily.iloc[0] = last.iloc[0] - equity0          # the first day counts too
    lab = labels.reindex(daily.index).ffill()
    out = {}
    for name, grp in daily.groupby(lab):
        days = int(len(grp))
        pct = float(grp.sum() / equity0)
        out[str(name)] = {"days": days, "pnl_pct": pct, "annualised": pct / days * 365 if days else 0.0}
    return out


# ------------------------------------------------------------ monte carlo
def _cluster_boot(totals: np.ndarray, equity0: float, rng) -> dict:
    draws = rng.choice(totals, size=(MC_PATHS, len(totals)), replace=True)
    paths = draws.cumsum(axis=1)
    total = paths[:, -1] / equity0
    dd = (paths - np.maximum.accumulate(np.maximum(paths, 0.0), axis=1)).min(axis=1) / equity0
    return {"total": total, "dd": dd,
            "p": float(((draws.sum(axis=1) <= 0).sum() + 1) / (MC_PATHS + 1))}


def monte_carlo(trades: list[dict], equity0: float, seed: int = 0) -> dict:
    """Cluster bootstrap. Trades on correlated coins win and lose together, so
    resampling single trades overstates confidence. Whole UTC exit DAYS are
    resampled (with replacement, same number of days) for the return and drawdown
    distributions; the p-value is also computed on whole exit WEEKS, and the
    larger (more cautious) of the two is the one the luck check uses."""
    if len(trades) < 10:
        return {"n": len(trades), "p_value_mean_le_0": 1.0, "p_value_day_clustered": 1.0,
                "p_value_week_clustered": 1.0, "prob_loss": 1.0}
    pnl = pd.Series([t["pnl"] for t in trades], dtype=float,
                    index=pd.DatetimeIndex([pd.Timestamp(t["exit_time"]) for t in trades]))
    rng = np.random.default_rng(seed)
    days = pnl.groupby(pnl.index.floor("D")).sum().to_numpy()
    weeks = pnl.groupby(pnl.index.floor("D") - pd.to_timedelta(pnl.index.dayofweek, unit="D")).sum().to_numpy()
    d = _cluster_boot(days, equity0, rng)
    w = _cluster_boot(weeks, equity0, rng) if len(weeks) >= 8 else {"p": d["p"]}   # too few weeks to resample
    return {
        "n": int(len(pnl)), "exit_days": int(len(days)), "exit_weeks": int(len(weeks)), "paths": MC_PATHS,
        "total_return_p05": float(np.percentile(d["total"], 5)), "total_return_p50": float(np.percentile(d["total"], 50)),
        "total_return_p95": float(np.percentile(d["total"], 95)),
        "max_dd_p50": float(np.percentile(d["dd"], 50)), "max_dd_p95_worst": float(np.percentile(d["dd"], 5)),
        "prob_loss": float((d["total"] <= 0).mean()),
        "p_value_day_clustered": d["p"], "p_value_week_clustered": w["p"],
        "p_value_mean_le_0": max(d["p"], w["p"]),
    }


# ------------------------------------------------------------------ audit
def _slim(s: dict) -> dict:
    return {k: v for k, v in s.items() if k not in ("monthly",)}


def audit(strategy, market: Market, end: pd.Timestamp = VALIDATION_END,
          costs: Costs | None = None, risk: Risk | None = None, replay: bool = True) -> dict:
    with store.ceiling(end):                      # nothing at or after `end` can be read by any code below
        return _audit(strategy, market, end, costs or Costs(), risk or Risk(), replay)


def _audit(strategy, market: Market, end: pd.Timestamp, costs: Costs, risk: Risk, replay: bool) -> dict:
    eq0 = risk.equity0
    cells = grid_cells(strategy)
    intents = [fresh_instance(strategy).intents(market.data, dict(c)) for c in cells]   # one fresh object per cell
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
    res["leak_test"] = leak_test(strategy, market.data, full_by_cell=intents)

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

    delayed = [attach(market.base, {s: df.shift(1) for s, df in it.items()}) for it in intents]
    res["stress"] = {
        "fees_x2": stress(replace(costs, fee_mult=2.0)),
        "slippage_x2": stress(replace(costs, slip_mult=2.0)),
        # funding stress is one-sided: funding paid is doubled, funding received is left alone
        "funding_x2": stress(replace(costs, funding_paid_mult=2.0)),
        "all_costs_x2": stress(replace(costs, fee_mult=2.0, slip_mult=2.0, funding_paid_mult=2.0)),
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

    # regimes: scored on the VALIDATION quarters only; the all-quarters tables are for display
    reg = btc_regimes(market)
    res["regimes_trend"] = by_regime(eq_v, reg["trend"], eq0) if len(eq_v) else {}
    res["regimes_state"] = by_regime(eq_v, reg["state"], eq0) if len(eq_v) else {}
    res["regimes_trend_all"] = by_regime(eq_all, reg["trend"], eq0) if len(eq_all) else {}
    res["regimes_state_all"] = by_regime(eq_all, reg["state"], eq0) if len(eq_all) else {}
    res["monte_carlo"] = monte_carlo(tr_v, eq0)
    res["benchmark"] = buy_and_hold(market, DESIGN_END, end, costs, eq0)
    res["benchmark_wf_all"] = buy_and_hold(market, WF_START, end, costs, eq0)
    res["scores"] = scoring.score(v, res["regimes_trend"])
    res["gates"] = scoring.gates(res)
    # exhaustive look-ahead replay of every validation trade, only worth its cost for strategies that
    # pass everything else
    res["leak_replay"] = {"passed": True, "probes": 0, "skipped": True}
    if replay and res["gates"]["all_passed"] and tr_v:
        bounds = [(pd.Timestamp(c["test_start"], tz="UTC"), pd.Timestamp(c["test_end"], tz="UTC"), c["cell"])
                  for c in wf["chosen"]]

        def cell_for_time(ts: pd.Timestamp) -> int:
            for t0, t1, k in bounds:
                if t0 <= ts <= t1:
                    return k
            return 0
        res["leak_replay"] = leak_replay(strategy, market.data, tr_v, cell_for_time, cells, intents)
        res["gates"]["no_lookahead"] = res["gates"]["no_lookahead"] and res["leak_replay"]["passed"]
        res["gates"]["all_passed"] = all(v2 for k2, v2 in res["gates"].items() if k2 != "all_passed")
    res["_trades_validation"] = tr_v
    res["_trades_all"] = tr_all
    res["_equity_all"] = eq_all
    return res
