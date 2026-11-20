# cross_rs_leader_long

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, holds_one_bar_late, beats_holding. Score 7/25. Regime it needs: **trending**.

## The idea
Once a day, buy the two strongest coins of the month's top 10 on 14-day return, only while at least half the top 10 trade above their 200-hour average, and hold up to a week.

## Why the edge exists
Capital rotates slowly into the coins already leading, because allocators chase recent relative performance and leaders attract the marginal buyer while the market is healthy.

**Who is on the losing side:** Holders of laggards waiting for mean reversion, and shorts fading the leaders.

## Exact rules
- **Entry:** Decide once a day at the close of the 23:00 UTC bar. U = symbols in that month's top 10 with a valid close[t] and close[t-L]; skip the day if fewer than 8. mom = close[t]/close[t-L] - 1, ranked descending within U. breadth = share of the month's top-10 symbols with close[t] > SMA(close, 200). Go long at the next open (00:00 UTC) each symbol with rank <= 2 AND mom > 0 AND breadth >= 0.5. A signal on a symbol that already has a position is ignored by the engine.
- **Stop:** stop = close[t] * (1 - stop_k * dvol), dvol = ta.realized_vol(close, 168) * sqrt(24) (std of hourly log returns over 168 bars scaled to one day; about 5% away on BTC, 10% on alts). Fixed after entry, no trailing.
- **Exit:** exit=True at a daily decision bar (23:00 close) when the symbol's rank is worse than 5, filled at the next open; otherwise time stop max_hold = 168 bars. If the symbol drops out of the universe no exit signal fires and the time stop or the stop closes it.
- **Limit order life:** 1 bar(s). **Time stop:** 168 bars.
- **Default parameters:** `{"L": 336, "top": 2, "stop_k": 2.0, "exit_rank": 5, "breadth_min": 0.5, "breadth_ma": 200}`
- **Code:** `desk/strategies/s_cross_rs_leader_long.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -4.8% | -62.2% | -23.5% |
| Max drawdown | -15.9% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.22 | -0.61 | -0.33 |
| Sharpe | -0.42 | -0.84 | -0.41 |

- Trades: **147**, win rate 31%, average trade -0.07R, profit factor 0.86
- Fees paid $102, funding paid $29 (negative = received), gross P&L $-350
- **Worst month:** -3.8%. **Longest losing streak:** 22 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +14.5%, max drawdown -15.9%, 264 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +12.92% | 28 |
| 2024-01-01 | +1.71% | 31 |
| 2024-04-01 | -0.71% | 14 |
| 2024-07-01 | +1.51% | 27 |
| 2024-10-01 | +3.87% | 17 |
| 2025-01-01 | -2.90% | 14 |
| 2025-04-01 | +2.07% | 19 |
| 2025-07-01 | +0.67% | 43 |
| 2025-10-01 | -2.63% | 24 |
| 2026-01-01 | -7.61% | 32 |
| 2026-04-01 | +5.59% | 15 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -5.8% | -16.5% |
| Slippage doubled | -5.5% | -16.3% |
| Funding doubled | -5.5% | -16.3% |
| All costs doubled | -7.2% | -17.3% |
| Entered one bar late | -4.2% | -15.4% |
| Guardian switched off | -2.4% | -14.6% |
| No costs at all | -1.2% | -14.6% |

**Nearby settings:** 78% of 9 parameter combinations were profitable on the unseen window (median +0.7%, worst -2.1%, best +3.1%).

**Monte Carlo** (5000 reshuffles of the 147 unseen trades): 5th percentile return -18.8%, median -5.3%, chance of losing money 71%, bad-case drawdown -21.5%.

**Luck check:** p = 0.715 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -2.7% | -10.5% |
| bull | 86 | +5.6% | +23.9% |
| chop | 322 | -7.7% | -8.8% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -6.8% | -11.9% |
| trending | 217 | +5.5% | +9.2% |
| wild | 76 | -3.5% | -16.7% |

**The market that breaks it:** wild state (-16.7% annualised over 76 days).

**Earliest warning sign it is fading:** Top-2 minus basket forward 72h return, averaged over the trailing 90 daily samples, turns negative (design mean +55 bps), or 8 stop-outs in the last 10 trades while breadth stayed above 0.5.

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | **no** |
| Across 50+ trades? | yes |
| With fees doubled? | **no** |
| Does it hold across nearby settings? | yes |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | **no** |
| Does it beat simply holding, after costs? | **no** |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 1 | 1 | 3 | 1 | 1 | 7/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
It is long-only momentum with a breadth switch, so it carries market beta: every tested setting lost money in 2022 (-1.6% to -8.8%) and it will lose in a falling or choppy validation year. The proven edge is relative (leader minus basket, about 55 bps per 3 days); the engine cannot hedge it, so most of the design-window profit is the 2023-24 bull market. Overlap-adjusted t-stats are only about 2 and the relative hit rate is 50%, so the result depends on a few big winners. The breadth gate was added after seeing the ungated drawdown. It may fail the 'beats holding the basket' gate if validation is a bull run and the profit gate if it is a bear.
