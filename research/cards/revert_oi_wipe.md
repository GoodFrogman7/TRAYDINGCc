# revert_oi_wipe

**Verdict:** FAILED: trades_50_plus, nearby_settings_hold. Score 8/25. Regime it needs: **wild**.

## The idea
Buy when open interest collapses during a 3-hour drop of more than 3 sigma, and hold 12 hours.

## Why the edge exists
A collapse in open interest during a sharp drop means leveraged longs were forcibly closed, so the selling was mechanical and is finished.

**Who is on the losing side:** Liquidated longs, and late shorts who sell into the hole the liquidations left.

## Exact rules
- **Entry:** k = 3. mark = mark_close. sig168[t] = std of ln(mark[i]/mark[i-1]) over the 168 bars ending at t-1 (rolling(168).std().shift(1)). mz[t] = ln(mark[t]/mark[t-k]) / (sig168[t] * sqrt(k)). doi[t] = oi[t]/oi[t-k] - 1. thr[t] = doi.rolling(720, min_periods=240).quantile(0.01).shift(1). print_ok = abs(close[t]/mark_close[t] - 1) <= 0.003. Long if doi[t] < thr[t] and mz[t] < -3.0 and print_ok, with oi, mark_close and ATR all not NaN. Market order at the open of bar t+1.
- **Stop:** close[t] - stop_atr * ta.atr(df, 24)[t], stop_atr = 4.0. Fixed, no trailing.
- **Exit:** Time stop after 12 bars (max_hold = 12). No take-profit, no exit signal.
- **Limit order life:** 1 bar(s). **Time stop:** 12 bars.
- **Default parameters:** `{"k": 3, "z": 3.0, "q": 0.01, "stop_atr": 4.0}`
- **Code:** `desk/strategies/s_revert_oi_wipe.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | +2.8% | -62.2% | -23.5% |
| Max drawdown | -3.0% | -74.4% | -51.3% |
| Return / drawdown (annual) | 0.67 | -0.61 | -0.33 |
| Sharpe | 0.65 | -0.84 | -0.41 |

- Trades: **47**, win rate 60%, average trade +0.12R, profit factor 1.47
- Fees paid $56, funding paid $-5 (negative = received), gross P&L $330
- **Worst month:** -1.1%. **Longest losing streak:** 4 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +7.1%, max drawdown -4.1%, 121 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | -0.44% | 10 |
| 2024-01-01 | +2.95% | 20 |
| 2024-04-01 | +1.11% | 15 |
| 2024-07-01 | -2.04% | 14 |
| 2024-10-01 | +2.70% | 15 |
| 2025-01-01 | +2.99% | 15 |
| 2025-04-01 | +1.93% | 7 |
| 2025-07-01 | -0.20% | 4 |
| 2025-10-01 | -0.89% | 12 |
| 2026-01-01 | -1.18% | 7 |
| 2026-04-01 | +0.14% | 2 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | +2.2% | -3.3% |
| Slippage doubled | +2.6% | -3.1% |
| Funding doubled | +2.8% | -3.0% |
| All costs doubled | +2.0% | -3.4% |
| Entered one bar late | +4.3% | -2.5% |
| Guardian switched off | +2.8% | -3.0% |
| No costs at all | +3.5% | -2.8% |

**Nearby settings:** 44% of 9 parameter combinations were profitable on the unseen window (median -0.8%, worst -12.3%, best +2.8%).

**Monte Carlo** (5000 reshuffles of the 47 unseen trades): 5th percentile return -2.9%, median +2.7%, chance of losing money 23%, bad-case drawdown -4.7%.

**Luck check:** p = 0.234 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -2.7% | -10.3% |
| bull | 86 | +0.9% | +4.0% |
| chop | 322 | +4.5% | +5.1% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | +0.9% | +1.7% |
| trending | 217 | +3.2% | +5.4% |
| wild | 76 | -1.3% | -6.5% |

**The market that breaks it:** bear trend (-10.3% annualised over 94 days).

**Earliest warning sign it is fading:** Twelve-hour return after the last 20 signals averaging under +50 bps, or more than a third of trades stopped out (in design 10% were).

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | yes |
| Across 50+ trades? | **no** |
| With fees doubled? | yes |
| Does it hold across nearby settings? | **no** |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | yes |
| Does it beat simply holding, after costs? | yes |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 2 | 1 | 1 | 1 | 3 | 8/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Short history and no bear market in it; 2023 gave +2R and 2024 gave +15R. 63 distinct days, so it is barely significant once same-day trades count as one bet. It fires on the same crash days as revert_liq_flush and revert_cascade: treat the three as one bet. An OI collapse can be the first leg of a multi-day deleveraging, where buying the first flush loses a full 1R against an average win of about 0.4R. The 4-ATR stop after a crash sits 8-15% away. OI is an analytics series that may arrive late or be revised live.
