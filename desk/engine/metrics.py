"""Performance statistics from an equity curve and a trade list.

Position sizing does not compound by default (every trade risks the same
dollars), so returns are expressed as a fraction of starting equity and are
additive across time. All figures are AFTER fees, funding and slippage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def losing_streak(pnls: list[float]) -> int:
    best = cur = 0
    for p in pnls:
        cur = cur + 1 if p < 0 else 0
        best = max(best, cur)
    return best


def summarize(equity: pd.Series, trades: list[dict], equity0: float,
              gross: pd.Series | None = None) -> dict:
    """`equity` is the hourly mark-to-market equity over the evaluated window."""
    eq = equity.dropna()
    out: dict = {"bars": int(len(eq))}
    if len(eq) < 2:
        return {**out, "n_trades": 0, "total_return": 0.0, "sharpe": 0.0, "max_dd": 0.0, "annual_return": 0.0,
                "calmar": 0.0, "win_rate": 0.0, "avg_r": 0.0, "profit_factor": 0.0,
                "longest_losing_streak": 0, "worst_month": 0.0}
    start = float(equity0)        # the account's opening balance, not the first mark
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    pnl = float(eq.iloc[-1] - start)
    out["start"] = eq.index[0].isoformat()
    out["end"] = eq.index[-1].isoformat()
    out["years"] = round(years, 3)
    out["pnl_usd"] = pnl
    out["total_return"] = pnl / equity0
    out["annual_return"] = out["total_return"] / years if years > 0 else 0.0
    daily = eq.resample("1D").last().ffill()
    dchg = daily.diff()
    dchg.iloc[0] = daily.iloc[0] - start          # the first day counts too
    dret = dchg / equity0
    sd = float(dret.std())
    out["sharpe"] = float(dret.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0
    dsd = float(np.sqrt((dret.clip(upper=0.0) ** 2).mean())) if len(dret) else 0.0
    out["sortino"] = float(dret.mean() / dsd * np.sqrt(365)) if dsd > 0 else 0.0
    dd = (eq - eq.cummax().clip(lower=start)) / equity0
    out["max_dd"] = float(dd.min())
    out["calmar"] = out["annual_return"] / abs(out["max_dd"]) if out["max_dd"] < 0 else 0.0
    out["worst_day"] = float(dret.min()) if len(dret) else 0.0
    mlast = eq.resample("MS").last().ffill()
    monthly = mlast.diff()
    monthly.iloc[0] = mlast.iloc[0] - start
    monthly = monthly / equity0
    out["worst_month"] = float(monthly.min())
    out["best_month"] = float(monthly.max())
    out["pct_months_up"] = float((monthly > 0).mean())
    out["monthly"] = {k.strftime("%Y-%m"): round(float(v), 5) for k, v in monthly.items()}
    if gross is not None:
        g = gross.reindex(eq.index).fillna(0.0)
        out["exposure"] = float((g > 0).mean())
        out["avg_gross_leverage"] = float(g.mean() / equity0)

    n = len(trades)
    out["n_trades"] = n
    if n:
        p = np.array([t["pnl"] for t in trades], dtype=float)
        r = np.array([t["r"] for t in trades], dtype=float)
        wins, losses = p[p > 0], p[p < 0]
        out["win_rate"] = float((p > 0).mean())
        out["avg_r"] = float(r.mean())
        out["median_r"] = float(np.median(r))
        out["worst_r"] = float(r.min())
        out["profit_factor"] = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
        out["expectancy_usd"] = float(p.mean())
        out["longest_losing_streak"] = losing_streak(list(p))
        out["avg_bars_held"] = float(np.mean([t["bars_held"] for t in trades]))
        out["fees_usd"] = float(sum(t["fees"] for t in trades))
        out["funding_usd"] = float(sum(t["funding"] for t in trades))
        out["gross_pnl_usd"] = float(sum(t["pnl_gross"] for t in trades))
        out["long_pnl_usd"] = float(sum(t["pnl"] for t in trades if t["side"] > 0))
        out["short_pnl_usd"] = float(sum(t["pnl"] for t in trades if t["side"] < 0))
        out["n_long"] = int(sum(1 for t in trades if t["side"] > 0))
        out["maker_entry_share"] = float(np.mean([bool(t["maker_entry"]) for t in trades]))
        reasons: dict[str, int] = {}
        for t in trades:
            reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
        out["exit_reasons"] = reasons
        by_sym: dict[str, float] = {}
        for t in trades:
            by_sym[t["symbol"]] = by_sym.get(t["symbol"], 0.0) + t["pnl"]
        out["pnl_by_symbol"] = {k: round(v, 2) for k, v in sorted(by_sym.items(), key=lambda kv: -kv[1])}
    else:
        out.update(win_rate=0.0, avg_r=0.0, median_r=0.0, worst_r=0.0, profit_factor=0.0, expectancy_usd=0.0,
                   longest_losing_streak=0, avg_bars_held=0.0, fees_usd=0.0, funding_usd=0.0, gross_pnl_usd=0.0)
    return out
