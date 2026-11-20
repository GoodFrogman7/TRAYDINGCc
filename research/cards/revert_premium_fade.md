# revert_premium_fade

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding. Score 14/25. Regime it needs: **wild**.

## The idea
Fade the perp when its hour-average premium to the spot index is extreme: short above +0.3%, long below -0.3%, and get out when the premium is back inside 0.1% or after 8 hours.

## Why the edge exists
A perp trading far from its index is being pushed by one-sided leveraged flow, and arbitrage plus funding pull it back to the index within hours.

**Who is on the losing side:** Leveraged traders chasing the move on the perp at a price the spot market does not confirm.

## Exact rules
- **Entry:** At the close of bar t: prem = premium[t]; ATR = ta.atr(df, 24)[t]; print_ok = abs(close[t]/mark_close[t] - 1) <= 0.003 (the engine's next open is always this last print, so it must agree with the mark). If prem > +0.003 and print_ok: side = -1. If prem < -0.003 and print_ok: side = +1. No signal while premium, mark_close or ATR is NaN. Market order at the open of bar t+1 (limit = NaN).
- **Stop:** Long: close[t] - stop_atr * ATR[t]. Short: close[t] + stop_atr * ATR[t]. stop_atr = 3.0. Fixed at entry, no trailing.
- **Exit:** exit = True on every bar where abs(premium) < 0.001 (the dislocation is gone; closes at the next open). Otherwise time stop after 8 bars (max_hold = 8). No take-profit.
- **Limit order life:** 1 bar(s). **Time stop:** 8 bars.
- **Default parameters:** `{"prem": 0.003, "stop_atr": 3.0, "exit_prem": 0.001, "atr_n": 24, "print_tol": 0.003}`
- **Code:** `desk/strategies/s_revert_premium_fade.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -1.3% | -62.2% | -23.5% |
| Max drawdown | -2.6% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.36 | -0.61 | -0.33 |
| Sharpe | -0.41 | -0.84 | -0.41 |

- Trades: **90**, win rate 49%, average trade -0.03R, profit factor 0.87
- Fees paid $65, funding paid $-40 (negative = received), gross P&L $-104
- **Worst month:** -1.3%. **Longest losing streak:** 5 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +8.3%, max drawdown -5.6%, 268 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | -0.04% | 9 |
| 2024-01-01 | +4.75% | 127 |
| 2024-04-01 | +0.00% | 0 |
| 2024-07-01 | +5.74% | 27 |
| 2024-10-01 | -0.83% | 15 |
| 2025-01-01 | -0.76% | 8 |
| 2025-04-01 | -1.23% | 11 |
| 2025-07-01 | +0.08% | 3 |
| 2025-10-01 | +1.03% | 52 |
| 2026-01-01 | -0.74% | 10 |
| 2026-04-01 | +0.33% | 6 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -1.9% | -2.8% |
| Slippage doubled | -2.2% | -2.9% |
| Funding doubled | -1.3% | -2.6% |
| All costs doubled | -2.8% | -3.1% |
| Entered one bar late | +1.6% | -2.9% |
| Guardian switched off | -1.1% | -2.6% |
| No costs at all | -0.1% | -2.2% |

**Nearby settings:** 33% of 9 parameter combinations were profitable on the unseen window (median -0.4%, worst -2.3%, best +0.8%).

**Monte Carlo** (5000 reshuffles of the 90 unseen trades): 5th percentile return -5.9%, median -1.2%, chance of losing money 67%, bad-case drawdown -7.0%.

**Luck check:** p = 0.692 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +0.4% | +1.7% |
| bull | 86 | -0.4% | -1.8% |
| chop | 322 | -1.3% | -1.5% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -0.7% | -1.2% |
| trending | 217 | +0.4% | +0.7% |
| wild | 76 | -1.1% | -5.1% |

**The market that breaks it:** wild state (-5.1% annualised over 76 days).

**Earliest warning sign it is fading:** Mean gross return of the last 40 trades under +25 bps, or the one-bar-late version of those same trades turning negative (someone faster is taking the first hour).

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | **no** |
| Across 50+ trades? | yes |
| With fees doubled? | **no** |
| Does it hold across nearby settings? | **no** |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | yes |
| Does it beat simply holding, after costs? | **no** |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 1 | 5 | 2 | 4 | 2 | 14/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
The short leg earned nothing in 2022 and 2023; its profit is 2024, when 206 of its 279 trades happened, and 69 trades are one coin (INJ). Extreme premiums occur in 0.2-1% of hours and bunch into a few episodes, so a calm 16 months can miss the 50-trade gate. About 40% of the edge is in the first hour and one bar late halves the profit, so real slippage on thin alts can eat it. In a genuine squeeze a rich premium gets richer: stops will be hit hard and can gap. Funding before 2025-11 is an estimate and supplied about a fifth of the profit. If arbitrage has compressed Kraken's basis since 2024 the signal just stops firing.
