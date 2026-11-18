"""Rank audited strategies and write the leaderboard.

    python -m desk.audit.rank

Ranking: strategies that pass every gate first, then total score, then
validation return per unit of drawdown. A Holm correction across EVERY audited
strategy says which survivors are distinguishable from luck given how many
ideas were tried.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "results"


def load_results() -> list[dict]:
    out = []
    for p in sorted(OUT.glob("*.json")):
        if p.name.startswith(("leaderboard", "holdout", "ref_", "coinbase_subset", "verify")):
            continue
        out.append(json.loads(p.read_text()))
    return out


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm-Bonferroni: which hypotheses stay significant across the whole family."""
    order = sorted(pvals, key=pvals.get)
    m, keep, ok = len(order), {}, True
    for i, name in enumerate(order):
        ok = ok and pvals[name] <= alpha / (m - i)
        keep[name] = ok
    return keep


def family_size(n_audited: int) -> int:
    """Every idea the Hunter drafted counts as a test, including the ones it rejected
    on design-window evidence and that were therefore never audited."""
    p = ROOT / "research" / "ideas" / "ideas.json"
    return max(n_audited, len(json.loads(p.read_text()))) if p.exists() else n_audited


def rank(results: list[dict]) -> list[dict]:
    pvals = {r["name"]: r["monte_carlo"].get("p_value_mean_le_0", 1.0) for r in results}
    padded = dict(pvals)
    for k in range(family_size(len(results)) - len(results)):
        padded[f"__rejected_before_audit_{k}"] = 1.0
    sig = holm(padded)
    vp = ROOT / "research" / "verify" / "verdicts.json"
    verdicts = json.loads(vp.read_text()) if vp.exists() else {}
    rows = []
    for r in results:
        v, g = r["wf_validation"], r["gates"]
        rows.append({
            "name": r["name"], "regime": r["regime"], "idea": r["idea"],
            "passed": g["all_passed"], "failed_gates": [k for k, ok in g.items() if not ok and k != "all_passed"],
            "score": r["scores"]["total"], "scores": r["scores"],
            "val_return": v.get("total_return", 0.0), "val_annual": v.get("annual_return", 0.0),
            "val_max_dd": v.get("max_dd", 0.0), "val_calmar": v.get("calmar", 0.0), "val_sharpe": v.get("sharpe", 0.0),
            "val_trades": v.get("n_trades", 0), "val_win_rate": v.get("win_rate", 0.0), "val_avg_r": v.get("avg_r", 0.0),
            "val_losing_streak": v.get("longest_losing_streak", 0), "val_worst_month": v.get("worst_month", 0.0),
            "fees_x2_return": r["stress"]["fees_x2"]["total_return"],
            "one_bar_late_return": r["stress"]["one_bar_late"]["total_return"],
            "grid_share_profitable": r["neighbourhood"]["share_profitable"],
            "wf_all_return": r["wf_all"].get("total_return", 0.0), "wf_all_max_dd": r["wf_all"].get("max_dd", 0.0),
            "hold_basket_return": r["benchmark"]["basket"]["total_return"],
            "hold_btc_return": r["benchmark"]["btc"]["total_return"],
            "p_value": pvals[r["name"]], "survives_holm": sig[r["name"]],
            "mc_prob_loss": r["monte_carlo"].get("prob_loss", 1.0),
            "skeptic": (verdicts.get(r["name"]) or {}).get("verdict", ""),
            "skeptic_one_line": (verdicts.get(r["name"]) or {}).get("one_line", ""),
        })
    rows.sort(key=lambda x: (not x["passed"], -x["score"], -x["val_calmar"]))
    return rows


def to_markdown(rows: list[dict]) -> str:
    n_pass = sum(r["passed"] for r in rows)
    lines = [
        "# Leaderboard", "",
        f"{family_size(len(rows))} ideas drafted, {len(rows)} audited, {n_pass} passed every gate. "
        "Validation window 2025-01-01 to 2026-05-17, "
        "walk-forward, after fees, funding and slippage, $10,000 account risking 0.5% per trade.", "",
        "| # | Strategy | Gates | Score | Return | Max DD | Trades | Fees x2 | Grid + | p | Holm | Skeptic |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        gate = "pass" if r["passed"] else "FAIL " + ", ".join(r["failed_gates"])
        lines.append(
            f"| {i} | `{r['name']}` | {gate} | {r['score']}/25 | {r['val_return']:+.1%} | {r['val_max_dd']:.1%} | "
            f"{r['val_trades']} | {r['fees_x2_return']:+.1%} | {r['grid_share_profitable']:.0%} | "
            f"{r['p_value']:.3f} | {'yes' if r['survives_holm'] else 'no'} | {r['skeptic'].replace('_', ' ') or '-'} |")
    if rows:
        lines += ["", f"Buy and hold over the same window, after costs: top-10 basket "
                      f"{rows[0]['hold_basket_return']:+.1%}, BTC only {rows[0]['hold_btc_return']:+.1%}.",
                  "", "`p` = bootstrap probability that the average trade is not positive. `Holm` = still "
                      "significant after correcting for every idea drafted. `Skeptic` = verdict of an independent "
                      "attempt to refute each strategy that passed the gates (research/verify/verdicts.json)."]
        ref = [r for r in rows if r["skeptic"]]
        if ref:
            lines += ["", "## Skeptic verdicts"] + [f"- `{r['name']}`: {r['skeptic_one_line']}" for r in ref]
    return "\n".join(lines) + "\n"


def main() -> int:
    rows = rank(load_results())
    (OUT / "leaderboard.json").write_text(json.dumps(rows, indent=1))
    (OUT / "leaderboard.md").write_text(to_markdown(rows))
    print(to_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
