# trend_day_follow

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding. Score 7/25. Regime it needs: **trending**.

## The idea
After a 24-hour move larger than 2 trailing standard deviations on more than twice normal 24-hour volume, in the direction of the prior 14-day trend, enter with the move and hold for up to a week.

## Why the edge exists
A high-volume day that extends an existing trend marks new information that slower holders take days to act on, so the move keeps going over the following week.

**Who is on the losing side:** Traders who fade the big day expecting a snap-back, and holders positioned against the trend who cover or sell over the following days.

## Exact rules
- **Entry:** At the close of bar t, per symbol: r24 = close/close.shift(24)-1; sd = r24.rolling(720, min_periods=360).std().shift(24); v24 = volume.rolling(24, min_periods=24).sum(); vr = v24 / v24.shift(24).rolling(720, min_periods=360).mean(); tr = sign(ta.ret(close, L).shift(24)) (trend measured before the impulse day); atr = ta.atr(df, 24). LONG if r24 > k*sd and vr > v and tr > 0. SHORT if r24 < -k*sd and vr > v and tr < 0. No signal while any input is NaN. Market order at the next bar's open. Evaluated every bar; the engine's one-position-per-symbol rule de-duplicates, and re-entry after an exit is allowed if the condition still holds.
- **Stop:** Long: close[t] - stop_atr*atr[t]. Short: close[t] + stop_atr*atr[t]. Fixed, never trailed.
- **Exit:** Time stop after 168 bars (max_hold=168) or the protective stop. No take-profit, no signal exit.
- **Limit order life:** 1 bar(s). **Time stop:** 168 bars.
- **Default parameters:** `{"L": 336, "k": 2.0, "v": 2.0, "stop_atr": 5.0}`
- **Code:** `desk/strategies/s_trend_day_follow.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -3.6% | -62.2% | -23.5% |
| Max drawdown | -11.6% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.22 | -0.61 | -0.33 |
| Sharpe | -0.29 | -0.84 | -0.41 |

- Trades: **99**, win rate 34%, average trade -0.07R, profit factor 0.85
- Fees paid $45, funding paid $19 (negative = received), gross P&L $-293
- **Worst month:** -2.8%. **Longest losing streak:** 14 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +19.9%, max drawdown -11.6%, 233 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +4.55% | 39 |
| 2024-01-01 | +0.43% | 29 |
| 2024-04-01 | -0.91% | 18 |
| 2024-07-01 | +0.32% | 17 |
| 2024-10-01 | +19.11% | 31 |
| 2025-01-01 | +0.51% | 17 |
| 2025-04-01 | -1.95% | 19 |
| 2025-07-01 | +0.17% | 16 |
| 2025-10-01 | -4.50% | 18 |
| 2026-01-01 | +2.07% | 23 |
| 2026-04-01 | +0.15% | 6 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -4.0% | -11.7% |
| Slippage doubled | -3.8% | -11.7% |
| Funding doubled | -4.0% | -11.7% |
| All costs doubled | -4.7% | -11.9% |
| Entered one bar late | -5.2% | -11.8% |
| Guardian switched off | -2.5% | -11.7% |
| No costs at all | -2.6% | -11.3% |

**Nearby settings:** 12% of 8 parameter combinations were profitable on the unseen window (median -2.4%, worst -4.7%, best +0.4%).

**Monte Carlo** (5000 reshuffles of the 99 unseen trades): 5th percentile return -16.2%, median -3.8%, chance of losing money 67%, bad-case drawdown -18.1%.

**Luck check:** p = 0.674 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -3.2% | -12.4% |
| bull | 86 | +5.7% | +24.3% |
| chop | 322 | -6.1% | -6.9% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -0.5% | -0.8% |
| trending | 217 | -3.1% | -5.2% |
| wild | 76 | -0.0% | -0.0% |

**The market that breaks it:** bear trend (-12.4% annualised over 94 days).

**Earliest warning sign it is fading:** Win rate over the last 40 trades under 35% (design 45%) with the average winner under 1.2 R (design 1.5 R), or the median 72-hour move in the trade direction over the last 30 signals turning negative.

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
| 1 | 2 | 2 | 1 | 1 | 7/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Two quarters (2022 Q2 and 2024 Q4) made 29 of the 32 points; the other nine netted about zero and 2022 Q4 lost 10%. Each leg has a losing regime: longs lost in 2022, shorts lost in 2023 and 2024, so a choppy year can lose on both. Shorts give back 181 bps on average in the first 24 hours. Net-of-cost avg R is about 2.4 standard errors from zero before any allowance for the roughly 20 ideas tested. Tight stops with loose thresholds lose money. The Guardian's three-losses halt removed a third of the no-Guardian profit.
