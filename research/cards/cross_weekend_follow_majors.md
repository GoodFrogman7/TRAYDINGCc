# cross_weekend_follow_majors

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, holds_one_bar_late, beats_holding. Score 11/25. Regime it needs: **trending**.

## The idea
Trade BTC and ETH for 24 hours in the direction BTC moved over the weekend, entering at the Sunday 22:00 UTC open.

## Why the edge exists
Weekend moves happen without institutional desks; when they return on Monday they trade in the direction the weekend already revealed instead of fading it.

**Who is on the losing side:** Weekend traders who fade the move expecting Monday to reverse it.

## Exact rules
- **Entry:** Signal bar = the bar whose open time is Sunday 21:00 UTC (index.dayofweek==6 and index.hour==21). At its close compute w = PF_XBTUSD close[t] / PF_XBTUSD close[t-48] - 1. If abs(w) >= thr, open side = sign(w) in PF_XBTUSD and in PF_ETHUSD (both use BTC's w), market at the next open (Sunday 22:00 UTC). No entries on any other bar.
- **Stop:** stop = close[t] - side * stop_atr * ATR(24)[t], ATR = ta.atr(df, 24) on the symbol's own hourly bars (roughly 1.5-2.5% away on BTC).
- **Exit:** Time stop only: max_hold = 24 bars, so the position closes at the Monday 22:00 UTC open. No take-profit, no trailing stop.
- **Limit order life:** 1 bar(s). **Time stop:** 24 bars.
- **Default parameters:** `{"look": 48, "thr": 0.005, "stop_atr": 4.0, "sig_dow": 6, "sig_hour": 21}`
- **Code:** `desk/strategies/s_cross_weekend_follow_majors.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -2.0% | -62.2% | -23.5% |
| Max drawdown | -10.1% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.14 | -0.61 | -0.33 |
| Sharpe | -0.24 | -0.84 | -0.41 |

- Trades: **106**, win rate 44%, average trade -0.04R, profit factor 0.92
- Fees paid $213, funding paid $15 (negative = received), gross P&L $31
- **Worst month:** -3.6%. **Longest losing streak:** 14 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +11.8%, max drawdown -10.1%, 196 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +4.49% | 12 |
| 2024-01-01 | +4.59% | 26 |
| 2024-04-01 | +0.54% | 18 |
| 2024-07-01 | +2.62% | 18 |
| 2024-10-01 | +1.55% | 16 |
| 2025-01-01 | +0.24% | 18 |
| 2025-04-01 | -6.12% | 26 |
| 2025-07-01 | +1.42% | 10 |
| 2025-10-01 | +1.69% | 26 |
| 2026-01-01 | -0.01% | 12 |
| 2026-04-01 | +0.81% | 14 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -4.1% | -11.1% |
| Slippage doubled | -2.3% | -10.2% |
| Funding doubled | -2.2% | -10.2% |
| All costs doubled | -4.6% | -11.3% |
| Entered one bar late | -9.5% | -12.6% |
| Guardian switched off | -1.5% | -9.6% |
| No costs at all | +0.6% | -9.0% |

**Nearby settings:** 78% of 9 parameter combinations were profitable on the unseen window (median +2.2%, worst -5.6%, best +8.7%).

**Monte Carlo** (5000 reshuffles of the 106 unseen trades): 5th percentile return -12.9%, median -2.1%, chance of losing money 63%, bad-case drawdown -15.3%.

**Luck check:** p = 0.628 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +1.6% | +6.3% |
| bull | 86 | -2.2% | -9.4% |
| chop | 322 | -1.4% | -1.6% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -0.8% | -1.3% |
| trending | 217 | -1.1% | -1.8% |
| wild | 76 | -0.1% | -0.6% |

**The market that breaks it:** bull trend (-9.4% annualised over 86 days).

**Earliest warning sign it is fading:** Trailing 26-weekend hit rate of 'BTC's Monday 24h return has the weekend's sign' at or below 50%, or trailing 26-weekend mean follow-through under 25 bps (design: 61% and +122 bps). Any announcement that CME crypto futures or the spot ETFs trade through the weekend.

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
| 1 | 2 | 3 | 1 | 4 | 11/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
It is one calendar effect on 140 independent weekends, about 71 in the validation window. The 48h lookback is the best cell and its neighbours are half as strong (24h +62 bps, 60h +64 bps; engine with lookback 24: +5.2%), so the true edge is probably 60-80 bps, not 120. 2023Q4 alone is more than half the engine profit and 5 of 11 quarters lost. The 2022 hit rate is under 50%; that year is carried by the May and June crash weekends. ETH is much weaker than BTC (t 2.1, 1.3-1.8 one bar late). If the cause is the TradFi closure it can be removed by a venue decision: my recollection (not checked) is that CME announced round-the-clock crypto futures trading for 2026, which would fall inside validation. BTC and ETH are entered together, so a wrong weekend costs about 1% of equity.
