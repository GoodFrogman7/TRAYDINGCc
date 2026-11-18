# flow_weekend_dump_short

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding. Score 6/25. Regime it needs: **wild**.

## The idea
If the thin-liquidity weekend (Fri 22:00 to Sun 22:00 UTC) closed sharply down, short at the Sunday 22:00 UTC open and hold 24 hours into the Monday session.

## Why the edge exists
A weekend sell-off happens in thin books without institutional flow, so the de-risking, margin calls and liquidations it triggers only arrive when weekday liquidity returns on Monday.

**Who is on the losing side:** Weekend dip-buyers and leveraged longs who get liquidated into the Monday open.

## Exact rules
- **Entry:** All tradable symbols. Only on the bar whose OPEN time is Sunday `hour`:00 UTC (index.dayofweek == 6 and index.hour == hour). r = close/close.shift(1) - 1; sd = r.rolling(168, min_periods=100).std().shift(1); z48 = (close/close.shift(48) - 1) / (sd * sqrt(48)). If z48 <= -z and ta.atr(df, 24) is not NaN: side = -1, market at the next bar's open (limit = NaN).
- **Stop:** signal-bar close + stop_atr * ta.atr(df, 24)
- **Exit:** Time stop only: max_hold = 24 bars. No take-profit, no trail, no exit signal.
- **Limit order life:** 1 bar(s). **Time stop:** 24 bars.
- **Default parameters:** `{"z": 0.75, "hour": 21, "stop_atr": 3.0}`
- **Code:** `desk/strategies/s_flow_weekend_dump_short.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -12.4% | -62.2% | -23.5% |
| Max drawdown | -29.7% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.30 | -0.61 | -0.33 |
| Sharpe | -1.10 | -0.84 | -0.41 |

- Trades: **85**, win rate 24%, average trade -0.29R, profit factor 0.46
- Fees paid $112, funding paid $10 (negative = received), gross P&L $-1,118
- **Worst month:** -4.0%. **Longest losing streak:** 20 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): -4.4%, max drawdown -29.7%, 100 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +0.00% | 0 |
| 2024-01-01 | +0.00% | 0 |
| 2024-04-01 | -1.24% | 3 |
| 2024-07-01 | +8.86% | 6 |
| 2024-10-01 | +0.38% | 6 |
| 2025-01-01 | -0.75% | 21 |
| 2025-04-01 | -4.04% | 22 |
| 2025-07-01 | +1.03% | 2 |
| 2025-10-01 | +2.08% | 4 |
| 2026-01-01 | -8.71% | 23 |
| 2026-04-01 | -2.01% | 13 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -13.5% | -30.7% |
| Slippage doubled | -13.2% | -30.3% |
| Funding doubled | -12.6% | -29.8% |
| All costs doubled | -14.5% | -31.5% |
| Entered one bar late | -15.3% | -30.0% |
| Guardian switched off | -11.6% | -29.1% |
| No costs at all | -10.3% | -27.9% |

**Nearby settings:** 0% of 27 parameter combinations were profitable on the unseen window (median -23.4%, worst -32.7%, best -6.7%).

**Monte Carlo** (5000 reshuffles of the 85 unseen trades): 5th percentile return -23.8%, median -12.3%, chance of losing money 97%, bad-case drawdown -24.6%.

**Luck check:** p = 0.970 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -3.2% | -12.6% |
| bull | 86 | -0.5% | -2.0% |
| chop | 322 | -8.7% | -9.8% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | +4.4% | +7.8% |
| trending | 217 | -11.1% | -18.7% |
| wild | 76 | -5.7% | -27.4% |

**The market that breaks it:** wild state (-27.4% annualised over 76 days).

**Earliest warning sign it is fading:** Four consecutive signal weekends that lose, or the weekend-level mean over the trailing 12 signal weekends turning negative; also weekend volume rising toward weekday levels.

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
It is a crash-continuation payoff, not a steady edge. Five weekends (2022-05-08 LUNA, 2022-06-12 Celsius, 2023-05-07, 2024-08-04, 2023-09-10) made +59% of the +55%; without them the result is -4.2%. Half of the signal weekends lose. A 16-month test may hold two such Mondays or none, and with none it bleeds about -0.1% per weekend. At z 1.0 the evidence is cleaner but only ~31 trades in 16 months, below the 50-trade gate; z 0.75 passes the count by diluting the edge (weekend-level t 1.0). 2024 was already weak (+5.6%, all of it from 4 Aug). Signals arrive on up to 10 correlated symbols at once, so a Monday reversal costs up to the 3% daily halt. It is calendar-defined rather than built from the volume or liquidation columns, and the 21:00 hour was fixed before the hour profile was run but the 17:00 neighbour is much weaker.
