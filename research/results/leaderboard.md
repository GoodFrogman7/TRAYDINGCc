# Leaderboard

40 ideas drafted, 18 audited, 5 passed every gate. Validation window 2025-01-01 to 2026-05-17, walk-forward, after fees, funding and slippage, $10,000 account risking 0.5% per trade.

| # | Strategy | Gates | Score | Return | Max DD | Trades | Fees x2 | Grid + | p | Holm | Skeptic |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `trend_impulse_follow` | pass | 17/25 | +24.8% | -11.4% | 268 | +20.8% | 100% | 0.120 | no | refuted |
| 2 | `carry_deep_discount` | pass | 17/25 | +4.0% | -5.7% | 92 | +3.4% | 78% | 0.307 | no | - |
| 3 | `cross_weekend_follow_alts` | pass | 16/25 | +8.6% | -4.9% | 129 | +7.0% | 78% | 0.131 | no | refuted |
| 4 | `trend_quiet_grind` | pass | 16/25 | +10.4% | -12.2% | 135 | +9.5% | 83% | 0.271 | no | refuted |
| 5 | `cross_ratio_break` | pass | 13/25 | +7.0% | -13.2% | 328 | +5.5% | 67% | 0.335 | no | - |
| 6 | `revert_premium_fade` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding | 14/25 | -1.3% | -2.6% | 90 | -1.9% | 33% | 0.692 | no | - |
| 7 | `cross_weekend_follow_majors` | FAIL profit_after_costs, profit_fees_doubled, holds_one_bar_late, beats_holding | 11/25 | -2.0% | -10.1% | 106 | -4.1% | 78% | 0.628 | no | - |
| 8 | `revert_cascade` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding | 10/25 | -3.1% | -4.9% | 65 | -3.7% | 0% | 0.771 | no | - |
| 9 | `carry_oi_washout` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding | 9/25 | -0.6% | -6.2% | 60 | -1.3% | 33% | 0.562 | no | - |
| 10 | `flow_liquidity_vacuum_fade` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding | 9/25 | -5.1% | -6.8% | 106 | -5.6% | 0% | 0.875 | no | - |
| 11 | `revert_oi_wipe` | FAIL trades_50_plus, nearby_settings_hold | 8/25 | +2.8% | -3.0% | 47 | +2.2% | 44% | 0.234 | no | - |
| 12 | `flow_hot_breakdown_limit_fade` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding | 8/25 | -11.0% | -15.8% | 206 | -12.4% | 19% | 0.880 | no | - |
| 13 | `revert_liq_flush` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding | 8/25 | -9.3% | -11.7% | 87 | -10.3% | 0% | 0.977 | no | - |
| 14 | `cross_rs_leader_long` | FAIL profit_after_costs, profit_fees_doubled, holds_one_bar_late, beats_holding | 7/25 | -4.8% | -15.9% | 147 | -5.8% | 78% | 0.715 | no | - |
| 15 | `trend_day_follow` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding | 7/25 | -3.6% | -11.6% | 99 | -4.0% | 12% | 0.674 | no | - |
| 16 | `flow_weekend_dump_short` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding | 6/25 | -12.4% | -29.7% | 85 | -13.5% | 0% | 0.970 | no | - |
| 17 | `flow_stress_bid` | FAIL trades_50_plus, profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding | 6/25 | -2.6% | -5.5% | 25 | -2.8% | 19% | 0.747 | no | - |
| 18 | `carry_cascade_discount` | FAIL profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding | 6/25 | -8.7% | -16.6% | 90 | -9.5% | 0% | 0.951 | no | - |

Buy and hold over the same window, after costs: top-10 basket -62.2%, BTC only -23.5%.

`p` = bootstrap probability that the average trade is not positive. `Holm` = still significant after correcting for every idea drafted. `Skeptic` = verdict of an independent attempt to refute each strategy that passed the gates (research/verify/verdicts.json).

Passed the gates but not sent to a skeptic, because a luck p-value this weak already rules them out as champion: `carry_deep_discount` (p = 0.31), `cross_ratio_break` (p = 0.33).

## Skeptic verdicts
- `trend_impulse_follow`: No bug, no look-ahead and no cost problem was found, but the +24.8% is not evidence of an edge: random entries with the same exposure score the same (real result at the 51st percentile), half of it comes from the Guardian halt rather than the specified rules, it is negative without its best five days, and the Coinbase-only walk-forward makes +3.7% with a -25% drawdown and fails the fees-doubled gate.
- `cross_weekend_follow_alts`: The code is faithful, causal and its costs are realistic, but the +8.6% is not distinguishable from luck: it is one coin (XRP = 86%), three weekends and two quarters, it loses money exactly where its own thesis says it should win, and it should not be relied on as champion.
- `trend_quiet_grind`: No bug, no look-ahead and realistic costs, but the +10.4% cannot be told apart from luck (p = 0.27): it comes from two rallies (Apr-May and Jul 2025), vanishes if 3 of the 135 trades are removed, and the strategy has lost money since August 2025, so it should not be relied on as champion.
