# carry_cascade_discount

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding. Score 6/25. Regime it needs: **wild**.

## The idea
Buy a perp that trades unusually far below its index, but only when at least two of the tradable top-10 perps are at an unusual discount at the same time (a market-wide leverage flush, not coin-specific news).

## Why the edge exists
Cross-margined longs are liquidated at market in a cascade, pushing perps below index and price below where unforced sellers would trade; once the forced flow ends the gap closes and price rebounds.

**Who is on the losing side:** Over-leveraged longs being liquidated at market and late momentum shorts who sell the perp below index.

## Exact rules
- **Entry:** At the close of bar t, for every symbol u in data: pm_u = premium.rolling(pm_n=8, min_periods=8).mean(); med_u = pm_u.rolling(720, min_periods=360).median(); sd_u = premium.rolling(720, min_periods=360).std() (std of the RAW hourly premium, not of pm); z_u = (pm_u - med_u) / sd_u. Breadth B(t) = number of symbols u with z_u(t) <= -zb (zb fixed at 2.0) AND store.tradable_mask(u, index)[t] AND not bar_missing[t], summed on a union hourly index (absent symbol = 0). Go long symbol s at market on the open of t+1 when z_s(t) <= -z AND pm_s(t) < 0 AND B(t) >= k AND ta.atr(df,24)[t] is not NaN. The signal is emitted on every qualifying bar (no cooldown); the engine ignores it while a position is open.
- **Stop:** close[t] - stop_atr * ta.atr(df, 24)[t]  (default 3.0 ATR, typically 4-5% below entry)
- **Exit:** Time stop only: close at 36 bars (max_hold=36). No take-profit, no trailing stop, no exit signal.
- **Limit order life:** 1 bar(s). **Time stop:** 36 bars.
- **Default parameters:** `{"pm_n": 8, "norm_n": 720, "z": 2.0, "zb": 2.0, "k": 2, "atr_n": 24, "stop_atr": 3.0}`
- **Code:** `desk/strategies/s_carry_cascade_discount.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -8.7% | -62.2% | -23.5% |
| Max drawdown | -16.6% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.38 | -0.61 | -0.33 |
| Sharpe | -0.84 | -0.84 | -0.41 |

- Trades: **90**, win rate 34%, average trade -0.19R, profit factor 0.58
- Fees paid $77, funding paid $-31 (negative = received), gross P&L $-825
- **Worst month:** -3.8%. **Longest losing streak:** 24 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +5.8%, max drawdown -16.6%, 155 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +1.42% | 3 |
| 2024-01-01 | +4.00% | 13 |
| 2024-04-01 | +3.74% | 25 |
| 2024-07-01 | +8.36% | 15 |
| 2024-10-01 | -2.96% | 9 |
| 2025-01-01 | +0.41% | 15 |
| 2025-04-01 | +1.02% | 15 |
| 2025-07-01 | -1.20% | 6 |
| 2025-10-01 | -4.02% | 19 |
| 2026-01-01 | -4.92% | 35 |
| 2026-04-01 | +0.00% | 0 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -9.5% | -17.2% |
| Slippage doubled | -9.2% | -17.0% |
| Funding doubled | -8.7% | -16.6% |
| All costs doubled | -10.0% | -17.6% |
| Entered one bar late | -7.7% | -18.1% |
| Guardian switched off | -7.8% | -16.8% |
| No costs at all | -7.8% | -15.9% |

**Nearby settings:** 0% of 18 parameter combinations were profitable on the unseen window (median -5.1%, worst -20.4%, best -0.5%).

**Monte Carlo** (5000 reshuffles of the 90 unseen trades): 5th percentile return -18.8%, median -9.1%, chance of losing money 91%, bad-case drawdown -19.9%.

**Luck check:** p = 0.951 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -3.5% | -13.4% |
| bull | 86 | +1.5% | +6.2% |
| chop | 322 | -6.7% | -7.6% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -11.5% | -20.0% |
| trending | 217 | +3.2% | +5.4% |
| wild | 76 | -0.4% | -2.1% |

**The market that breaks it:** ranging state (-20.0% annualised over 209 days).

**Earliest warning sign it is fading:** The breadth==1 control starts doing as well as breadth>=2, or the median 36h return of the last 15 cascade trades is below zero; also discounts closing within an hour so the 8h z rarely reaches -2 (events per quarter falling well under ~15).

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | **no** |
| Across 50+ trades? | yes |
| With fees doubled? | **no** |
| Does it hold across nearby settings? | **no** |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | **no** |
| Does it beat simply holding, after costs? | **no** |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 1 | 1 | 2 | 1 | 1 | 6/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Only 59 independent entry days in 33 months and the best 5 days are 67% of total R, so a 16-month test rests on ~30 days and a handful decide it. 2024 supplied two thirds of the profit; in the 2022 bear it made +3.8%, not +23%. It is threshold-sensitive in one place: loosening the BREADTH threshold to z<=-1.5 collapses avgR to 0.05-0.10 (2022 negative) and k=4 gives 0.12. It buys falling knives: a cascade that keeps going (exchange failure, depeg) stops out every position on the same day. Alts carry the edge and their real slippage in those hours is worse than average. Long-only.
