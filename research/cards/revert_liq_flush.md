# revert_liq_flush

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding. Score 8/25. Regime it needs: **wild**.

## The idea
Buy after an hour that combines a liquidation-volume spike with a bar of -3 sigma or worse, and hold 12 hours.

## Why the edge exists
Forced liquidations sell at any price; once the forced flow is done the price recovers part of the move because no one chose to sell there.

**Who is on the losing side:** Liquidated longs and momentum sellers who join at the low of a forced move.

## Exact rules
- **Entry:** mark = mark_close. sig168[t] = std of hourly mark log returns over the 168 bars ending at t-1. mz1[t] = ln(mark[t]/mark[t-1]) / sig168[t]. liq_usd[t] = liq_vol[t] * close[t]. q99[t] = liq_usd.rolling(720, min_periods=240).quantile(0.99).shift(1). print_ok = abs(close[t]/mark_close[t] - 1) <= 0.003. Long if liq_usd[t] > 2.0 * q99[t] and q99[t] > 0 and mz1[t] < -3.0 and print_ok, ATR not NaN. Market order at the open of bar t+1.
- **Stop:** close[t] - stop_atr * ta.atr(df, 24)[t], stop_atr = 4.0. Fixed, no trailing.
- **Exit:** Time stop after 12 bars (max_hold = 12). No take-profit, no exit signal.
- **Limit order life:** 1 bar(s). **Time stop:** 12 bars.
- **Default parameters:** `{"z": 3.0, "liq_mult": 2.0, "stop_atr": 4.0}`
- **Code:** `desk/strategies/s_revert_liq_flush.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -9.3% | -62.2% | -23.5% |
| Max drawdown | -11.7% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.58 | -0.61 | -0.33 |
| Sharpe | -1.52 | -0.84 | -0.41 |

- Trades: **87**, win rate 47%, average trade -0.21R, profit factor 0.42
- Fees paid $95, funding paid $-4 (negative = received), gross P&L $-841
- **Worst month:** -4.7%. **Longest losing streak:** 9 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): -6.0%, max drawdown -13.1%, 184 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +0.95% | 21 |
| 2024-01-01 | +2.38% | 14 |
| 2024-04-01 | -0.04% | 29 |
| 2024-07-01 | -0.55% | 20 |
| 2024-10-01 | +0.58% | 13 |
| 2025-01-01 | -1.44% | 6 |
| 2025-04-01 | -1.51% | 16 |
| 2025-07-01 | -1.30% | 11 |
| 2025-10-01 | -1.78% | 22 |
| 2026-01-01 | -4.31% | 24 |
| 2026-04-01 | +1.02% | 8 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -10.3% | -12.5% |
| Slippage doubled | -9.8% | -12.0% |
| Funding doubled | -9.4% | -11.7% |
| All costs doubled | -10.8% | -12.8% |
| Entered one bar late | -5.2% | -9.8% |
| Guardian switched off | -8.9% | -11.3% |
| No costs at all | -7.9% | -10.6% |

**Nearby settings:** 0% of 9 parameter combinations were profitable on the unseen window (median -13.5%, worst -16.5%, best -7.8%).

**Monte Carlo** (5000 reshuffles of the 87 unseen trades): 5th percentile return -18.1%, median -9.2%, chance of losing money 97%, bad-case drawdown -18.7%.

**Luck check:** p = 0.977 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -0.4% | -1.6% |
| bull | 86 | +0.1% | +0.5% |
| chop | 322 | -9.0% | -10.2% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -1.1% | -1.9% |
| trending | 217 | -7.8% | -13.2% |
| wild | 76 | -0.4% | -2.1% |

**The market that breaks it:** trending state (-13.2% annualised over 217 days).

**Earliest warning sign it is fading:** Twelve-hour return after the last 30 signals averaging under +30 bps, i.e. below round-trip cost on alts.

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
| 1 | 2 | 2 | 2 | 1 | 8/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
It is thin: +0.06R per trade, not significant once same-day trades are clustered, and negative in 2022. The bps edge is steady but the stop has to be 4 ATR wide to survive, which shrinks every win to a fraction of R while each stop costs a full R. Nothing on BTC or ETH. One bar late halves it. Same crash days as revert_oi_wipe and revert_cascade. Liquidation volume is a venue analytics feed that may lag live.
