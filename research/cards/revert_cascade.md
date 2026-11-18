# revert_cascade

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding. Score 10/25. Regime it needs: **wild**.

## The idea
Buy a coin that is down more than 4.5 sigma over 6 hours when bitcoin is also down more than 3 sigma over the same 6 hours, and hold 12 hours.

## Why the edge exists
A market-wide cascade forces sales of everything at once, pushing individual coins further than their own news justifies, and they rebound when the forced selling stops.

**Who is on the losing side:** Forced sellers across the market and traders who short the last leg of a cascade.

## Exact rules
- **Entry:** mark = mark_close. sig168[t] = std of hourly mark log returns over the 168 bars ending at t-1. mz6[t] = ln(mark[t]/mark[t-6]) / (sig168[t] * sqrt(6)), computed per symbol. btc6[t] = the same quantity for PF_XBTUSD, reindexed to the symbol's bars. print_ok = abs(close[t]/mark_close[t] - 1) <= 0.003. Long if mz6[t] < -4.5 and btc6[t] < -3.0 and print_ok, ATR not NaN. Market order at the open of bar t+1.
- **Stop:** close[t] - stop_atr * ta.atr(df, 24)[t], stop_atr = 4.0. Fixed, no trailing.
- **Exit:** Time stop after 12 bars (max_hold = 12). No take-profit, no exit signal.
- **Limit order life:** 1 bar(s). **Time stop:** 12 bars.
- **Default parameters:** `{"k": 6, "z": 4.5, "zb": 3.0, "stop_atr": 4.0}`
- **Code:** `desk/strategies/s_revert_cascade.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -3.1% | -62.2% | -23.5% |
| Max drawdown | -4.9% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.45 | -0.61 | -0.33 |
| Sharpe | -0.65 | -0.84 | -0.41 |

- Trades: **65**, win rate 55%, average trade -0.09R, profit factor 0.67
- Fees paid $61, funding paid $-3 (negative = received), gross P&L $-247
- **Worst month:** -2.9%. **Longest losing streak:** 11 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): -2.2%, max drawdown -9.1%, 129 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +0.09% | 8 |
| 2024-01-01 | +5.09% | 19 |
| 2024-04-01 | -5.01% | 21 |
| 2024-07-01 | +0.64% | 15 |
| 2024-10-01 | +0.05% | 1 |
| 2025-01-01 | -0.14% | 15 |
| 2025-04-01 | -0.27% | 7 |
| 2025-07-01 | +0.00% | 0 |
| 2025-10-01 | -1.25% | 12 |
| 2026-01-01 | -1.67% | 27 |
| 2026-04-01 | +0.28% | 4 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -3.7% | -5.2% |
| Slippage doubled | -3.3% | -5.1% |
| Funding doubled | -3.1% | -4.9% |
| All costs doubled | -4.0% | -5.4% |
| Entered one bar late | +0.8% | -4.3% |
| Guardian switched off | -0.0% | -4.3% |
| No costs at all | -2.2% | -4.4% |

**Nearby settings:** 0% of 9 parameter combinations were profitable on the unseen window (median -3.6%, worst -6.1%, best -3.0%).

**Monte Carlo** (5000 reshuffles of the 65 unseen trades): 5th percentile return -9.8%, median -2.8%, chance of losing money 77%, bad-case drawdown -10.7%.

**Luck check:** p = 0.771 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +1.6% | +6.1% |
| bull | 86 | +0.8% | +3.2% |
| chop | 322 | -5.4% | -6.1% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | +0.4% | +0.7% |
| trending | 217 | -3.8% | -6.4% |
| wild | 76 | +0.3% | +1.6% |

**The market that breaks it:** trending state (-6.4% annualised over 217 days).

**Earliest warning sign it is fading:** Two consecutive cascade days where the basket of signals closes below entry after 12 hours.

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
| 1 | 4 | 2 | 2 | 1 | 10/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
This is 34 bets, not 121: clustered t-stat 1.0, which is not distinguishable from luck. It lost in the one bear year (2022: 14 trades, 29% winners), because in a bear market the first flush is followed by another. Up to ten coins signal in the same hour, so one failed bounce trips the three-losses or -3% daily Guardian and closes everything at the low. Design pace is about 60 trades per 16 months, close to the 50-trade gate. It is the same crash days as the two ideas above; I rank it last of the tradeable ones and would not fund it on its own.
