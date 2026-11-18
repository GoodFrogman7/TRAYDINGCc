"""Strategy cards, generated from audit results so no number is typed by hand.

    python -m desk.audit.cards            # one card per audited strategy -> research/cards/<name>.md
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "research" / "results"
CARDS = ROOT / "research" / "cards"
IDEAS = ROOT / "research" / "ideas" / "ideas.json"

GATE_QUESTIONS = [
    ("profit_after_costs", "Does it win on data it has never seen, after fees and funding?"),
    ("trades_50_plus", "Across 50+ trades?"),
    ("profit_fees_doubled", "With fees doubled?"),
    ("nearby_settings_hold", "Does it hold across nearby settings?"),
    ("no_lookahead", "Free of look-ahead?"),
    ("beats_holding", "Does it beat simply holding, after costs?"),
]


def pct(x: float, d: int = 1) -> str:
    return f"{x:+.{d}%}"


def card(r: dict, idea: dict | None, holdout: dict | None, rank_row: dict | None) -> str:
    idea = idea or {}
    v, a, g, s = r["wf_validation"], r["wf_all"], r["gates"], r["scores"]
    b = r["benchmark"]
    L: list[str] = []
    verdict = "PASSED every gate" if g["all_passed"] else "FAILED: " + ", ".join(
        k for k, ok in g.items() if not ok and k != "all_passed")
    L += [f"# {r['name']}", "", f"**Verdict:** {verdict}. Score {s['total']}/25. Regime it needs: **{r['regime']}**.", ""]
    L += ["## The idea", r["idea"], "", "## Why the edge exists", r["cause"], "",
          "**Who is on the losing side:** " + r["loser"], ""]
    L += ["## Exact rules",
          f"- **Entry:** {idea.get('entry', 'see module docstring')}",
          f"- **Stop:** {idea.get('stop', 'see module docstring')}",
          f"- **Exit:** {idea.get('exit', 'see module docstring')}",
          f"- **Limit order life:** {r['valid_bars']} bar(s). **Time stop:** "
          f"{str(r['max_hold']) + ' bars' if r['max_hold'] else 'none'}.",
          f"- **Default parameters:** `{json.dumps(r['default_params'])}`",
          f"- **Code:** `desk/strategies/s_{r['name'].removeprefix('s_')}.py`", ""]
    risk = r["risk"]
    L += ["## Position size",
          f"Each trade risks {risk['risk_per_trade']:.1%} of a ${risk['equity0']:,.0f} account "
          f"(${risk['equity0'] * risk['risk_per_trade']:,.0f}) between entry and stop. One position's notional is "
          "capped at 1x equity and total exposure at 3x. Sizes do not compound.", ""]
    L += ["## Results after fees, funding and slippage",
          f"Unseen data, walk-forward, {v.get('start', '')[:10]} to {v.get('end', '')[:10]}:", "",
          "| | Strategy | Hold top-10 basket | Hold BTC |", "|---|---|---|---|",
          f"| Total return | {pct(v.get('total_return', 0))} | {pct(b['basket']['total_return'])} | {pct(b['btc']['total_return'])} |",
          f"| Max drawdown | {v.get('max_dd', 0):.1%} | {b['basket']['max_dd']:.1%} | {b['btc']['max_dd']:.1%} |",
          f"| Return / drawdown (annual) | {v.get('calmar', 0):.2f} | {b['basket']['calmar']:.2f} | {b['btc']['calmar']:.2f} |",
          f"| Sharpe | {v.get('sharpe', 0):.2f} | {b['basket']['sharpe']:.2f} | {b['btc']['sharpe']:.2f} |", "",
          f"- Trades: **{v.get('n_trades', 0)}**, win rate {v.get('win_rate', 0):.0%}, average trade "
          f"{v.get('avg_r', 0):+.2f}R, profit factor {v.get('profit_factor', 0):.2f}",
          f"- Fees paid ${v.get('fees_usd', 0):,.0f}, funding paid ${v.get('funding_usd', 0):,.0f} "
          f"(negative = received), gross P&L ${v.get('gross_pnl_usd', 0):,.0f}",
          f"- **Worst month:** {pct(v.get('worst_month', 0))}. **Longest losing streak:** "
          f"{v.get('longest_losing_streak', 0)} trades.", ""]
    L += ["## Walk-forward",
          f"Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters "
          f"({a.get('start', '')[:10]} to {a.get('end', '')[:10]}): {pct(a.get('total_return', 0))}, max drawdown "
          f"{a.get('max_dd', 0):.1%}, {a.get('n_trades', 0)} trades.", "",
          "| Quarter | Return | Trades |", "|---|---|---|"]
    L += [f"| {q['quarter']} | {pct(q['ret'], 2)} | {q['trades']} |" for q in r["wf_by_quarter"]]
    st = r["stress"]
    L += ["", "## Stress tests (same unseen window)",
          "| Test | Return | Max drawdown |", "|---|---|---|"]
    for k, lab in [("fees_x2", "Fees doubled"), ("slippage_x2", "Slippage doubled"), ("funding_x2", "Funding doubled"),
                   ("all_costs_x2", "All costs doubled"), ("one_bar_late", "Entered one bar late"),
                   ("guardian_off", "Guardian switched off"), ("no_costs", "No costs at all")]:
        L.append(f"| {lab} | {pct(st[k]['total_return'])} | {st[k]['max_dd']:.1%} |")
    nb, mc = r["neighbourhood"], r["monte_carlo"]
    L += ["", f"**Nearby settings:** {nb['share_profitable']:.0%} of {nb['cells']} parameter combinations were "
              f"profitable on the unseen window (median {pct(nb['median_return'])}, worst {pct(nb['worst_return'])}, "
              f"best {pct(nb['best_return'])}).",
          "", f"**Monte Carlo** ({mc.get('paths', 0)} reshuffles of the {mc.get('n', 0)} unseen trades): 5th percentile "
              f"return {pct(mc.get('total_return_p05', 0))}, median {pct(mc.get('total_return_p50', 0))}, chance of "
              f"losing money {mc.get('prob_loss', 1):.0%}, bad-case drawdown {mc.get('max_dd_p95_worst', 0):.1%}."]
    if rank_row:
        L += ["", f"**Luck check:** p = {rank_row['p_value']:.3f} that the average trade is not positive; "
                  f"{'survives' if rank_row['survives_holm'] else 'does NOT survive'} correction for every idea tested."]
    L += ["", "## How it behaved by market", "| BTC 30-day trend | Days | P&L | Annualised |", "|---|---|---|---|"]
    for k, x in sorted(r["regimes_trend"].items()):
        L.append(f"| {k} | {x['days']} | {pct(x['pnl_pct'])} | {pct(x['annualised'])} |")
    L += ["", "| Market state | Days | P&L | Annualised |", "|---|---|---|---|"]
    for k, x in sorted(r["regimes_state"].items()):
        L.append(f"| {k} | {x['days']} | {pct(x['pnl_pct'])} | {pct(x['annualised'])} |")
    allreg = {**{f"{k} trend": x for k, x in r["regimes_trend"].items()},
              **{f"{k} state": x for k, x in r["regimes_state"].items()}}
    if allreg:
        worst = min(allreg, key=lambda k: allreg[k]["annualised"])
        L += ["", f"**The market that breaks it:** {worst} ({pct(allreg[worst]['annualised'])} annualised over "
                  f"{allreg[worst]['days']} days)."]
    L += ["", "**Earliest warning sign it is fading:** " + idea.get("fading_sign", "not specified by the Hunter"), ""]
    if holdout:
        h = holdout["holdout"]
        L += ["## Sealed holdout (opened once)",
              f"{holdout['window'][0][:10]} to {holdout['window'][1][:10]}: {pct(h.get('total_return', 0))}, max drawdown "
              f"{h.get('max_dd', 0):.1%}, {h.get('n_trades', 0)} trades; fees doubled {pct(holdout['fees_x2']['total_return'])}. "
              f"Holding the basket: {pct(holdout['benchmark']['basket']['total_return'])}; BTC: "
              f"{pct(holdout['benchmark']['btc']['total_return'])}. **{'Passed' if holdout['passed'] else 'Failed'}.**", ""]
    L += ["## Final check", "| Question | Answer |", "|---|---|"]
    L += [f"| {q} | {'yes' if g[k] else '**no**'} |" for k, q in GATE_QUESTIONS]
    L += ["", "## Scores (1-5)", "| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |",
          "|---|---|---|---|---|---|",
          f"| {s['oos_profit']} | {s['max_drawdown']} | {s['trade_count']} | {s['losing_streak']} | {s['bear_chop']} | {s['total']}/25 |",
          "", "## Data",
          f"Source {r['data_source']} (public API), bars up to {r['data_asof']}. Funding before about 2025-11 is an "
          "estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.", "",
          "## WHY THIS COULD FAIL", idea.get("why_it_could_fail", "not specified"), ""]
    extra = idea.get("auditor_notes")
    if extra:
        L += [extra, ""]
    return "\n".join(L)


def main() -> int:
    CARDS.mkdir(parents=True, exist_ok=True)
    ideas = {}
    if IDEAS.exists():
        for i in json.loads(IDEAS.read_text()):
            ideas[i["id"]] = i
    lb = {}
    if (RES / "leaderboard.json").exists():
        lb = {x["name"]: x for x in json.loads((RES / "leaderboard.json").read_text())}
    n = 0
    for p in sorted(RES.glob("*.json")):
        if p.name.startswith(("leaderboard", "holdout", "ref_")):
            continue
        r = json.loads(p.read_text())
        hp = RES / f"holdout_{r['name']}.json"
        hold = json.loads(hp.read_text()) if hp.exists() else None
        key = r["name"].removeprefix("s_")
        (CARDS / f"{r['name']}.md").write_text(card(r, ideas.get(key) or ideas.get(r["name"]), hold, lb.get(r["name"])))
        n += 1
    print(f"wrote {n} cards to {CARDS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
