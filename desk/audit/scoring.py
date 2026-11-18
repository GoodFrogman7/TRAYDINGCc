"""Gates and 1-5 scores. Thresholds were fixed before any strategy was tested
(see docs/PROTOCOL.md) and must not be tuned to make a favourite pass."""
from __future__ import annotations

MIN_TRADES = 50
MIN_GRID_PROFITABLE = 0.60


def _band(x: float, cuts: list[float]) -> int:
    """1 + number of cut points x clears (cuts ascending) -> 1..5."""
    return 1 + sum(1 for c in cuts if x > c)


def score(v: dict, regimes: dict) -> dict:
    """`v` = walk-forward summary on the VALIDATION quarters (after costs)."""
    s = {
        "oos_profit": _band(v.get("annual_return", 0.0), [0.0, 0.03, 0.08, 0.15]),
        "max_drawdown": _band(-abs(v.get("max_dd", 0.0)), [-0.15, -0.10, -0.06, -0.03]),
        "trade_count": _band(v.get("n_trades", 0), [49.5, 99.5, 199.5, 399.5]),
        "losing_streak": _band(-v.get("longest_losing_streak", 99), [-11.5, -8.5, -6.5, -4.5]),
    }
    bear = regimes.get("bear", {}).get("annualised", 0.0)
    chop = regimes.get("chop", {}).get("annualised", 0.0)
    total = regimes.get("bear", {}).get("pnl_pct", 0.0) + regimes.get("chop", {}).get("pnl_pct", 0.0)
    if bear > 0 and chop > 0:
        s["bear_chop"] = 5
    elif total > 0 and min(bear, chop) > -0.02:
        s["bear_chop"] = 4
    elif total > 0:
        s["bear_chop"] = 3
    elif min(bear, chop) > -0.05:
        s["bear_chop"] = 2
    else:
        s["bear_chop"] = 1
    s["total"] = sum(s.values())
    return s


def gates(res: dict) -> dict:
    v = res["wf_validation"]
    g = {
        "no_lookahead": bool(res["leak_test"]["passed"]),
        "trades_50_plus": v.get("n_trades", 0) >= MIN_TRADES,
        "profit_after_costs": v.get("total_return", 0.0) > 0,
        "profit_fees_doubled": res["stress"]["fees_x2"].get("total_return", 0.0) > 0,
        "nearby_settings_hold": res["neighbourhood"]["share_profitable"] >= MIN_GRID_PROFITABLE,
        "beats_holding": v.get("calmar", 0.0) > res["benchmark"]["basket"].get("calmar", 0.0)
        and v.get("total_return", 0.0) > 0,
    }
    g["all_passed"] = all(g.values())
    return g
